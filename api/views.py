import secrets
import base64
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Avg, Count, F
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


class BookPagination(PageNumberPagination):
    """Bosh sahifa va admin uchun sahifalashtirish."""
    page_size = 24
    page_size_query_param = 'page_size'
    max_page_size = 10000

from .models import (
    Library,
    Section,
    Author,
    Book,
    Reader,
    Issue,
    Reservation,
    ReaderLibraryCard,
    BookRating,
    BookFavourite,
)
from .permissions import IsAdminTokenOrReadOnly
from .serializers import (
    LibrarySerializer,
    SectionSerializer,
    AuthorSerializer,
    BookSerializer,
    BookFavouriteSerializer,
    ReaderSerializer,
    ReaderRegisterSerializer,
    ReaderLoginSerializer,
    IssueSerializer,
    ReservationSerializer,
    ReaderLibraryCardSerializer,
    BookRatingSerializer,
)


def _resolve_reader_by_token(request):
    token = request.headers.get('X-Reader-Token')
    if not token:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.lower().startswith('bearer '):
            token = auth_header[7:].strip()
    if not token:
        return None
    return Reader.objects.filter(session_token=token).first()


def _is_admin_request(request):
    if request.user and request.user.is_staff:
        return True
    token = request.headers.get('X-Admin-Token', '')
    return bool(token) and token == getattr(settings, 'ADMIN_API_TOKEN', '')


def _purge_expired_reservations():
    """Muddati o'tgan bronlarni avtomatik o'chiradi. Har so'rovda chaqiriladi."""
    try:
        Reservation.objects.filter(expires_at__lte=timezone.now()).delete()
    except Exception:
        # Migration hali qo'llanmagan bo'lishi mumkin — sukut bilan o'tkazib yuboramiz
        pass


from rest_framework.decorators import api_view, permission_classes


@api_view(['GET'])
@permission_classes([AllowAny])
def statistics_view(request):
    """Umumiy tizim statistikasi — Drogon frontend / Desktop ilova uchun."""
    return Response({
        'total_books':        Book.objects.count(),
        'total_readers':      Reader.objects.count(),
        'total_reservations': Reservation.objects.count(),
        'total_issues':       Issue.objects.count(),
        'total_libraries':    Library.objects.count(),
        'total_sections':     Section.objects.count(),
        'total_authors':      Author.objects.count(),
        'pending_readers':    Reader.objects.filter(is_active=False).count(),
        'pending_cards':      ReaderLibraryCard.objects.filter(is_approved=False).count(),
    })


class LibraryViewSet(viewsets.ModelViewSet):
    queryset = Library.objects.all()
    serializer_class = LibrarySerializer
    permission_classes = [IsAdminTokenOrReadOnly]


class SectionViewSet(viewsets.ModelViewSet):
    queryset = Section.objects.all()
    serializer_class = SectionSerializer
    permission_classes = [IsAdminTokenOrReadOnly]


class AuthorViewSet(viewsets.ModelViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    permission_classes = [IsAdminTokenOrReadOnly]


class BookViewSet(viewsets.ModelViewSet):
    queryset = Book.objects.all()
    serializer_class = BookSerializer
    permission_classes = [IsAdminTokenOrReadOnly]
    pagination_class = BookPagination
    # Drogon frontend filtr/qidiruv/saralash uchun
    from rest_framework import filters as drf_filters
    filter_backends = [drf_filters.SearchFilter, drf_filters.OrderingFilter]
    search_fields = ['title', 'description', 'isbn', 'author__first_name', 'author__last_name']
    ordering_fields = ['title', 'view_count', 'reservation_count', 'issue_count', 'published_date']
    ordering = ['-view_count']

    def list(self, request, *args, **kwargs):
        ordering = request.query_params.get('ordering', '')
        user_lat = request.query_params.get('user_lat')
        user_lon = request.query_params.get('user_lon')
        # Masofa bo'yicha saralash maxsus rejimi
        if ordering in ('distance', '-distance') and user_lat and user_lon:
            from .serializers import _haversine_km
            qs = self.filter_queryset(self.get_queryset()).select_related('library', 'author')
            books = list(qs)

            def _dist(b):
                if b.library is None or b.library.latitude is None or b.library.longitude is None:
                    return 9.9e9  # Library yo'q — oxiriga
                d = _haversine_km(user_lat, user_lon, b.library.latitude, b.library.longitude)
                return d if d is not None else 9.9e9

            books.sort(key=_dist, reverse=(ordering == '-distance'))
            page = self.paginate_queryset(books)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                return self.get_paginated_response(serializer.data)
            serializer = self.get_serializer(books, many=True)
            return Response(serializer.data)
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        from django.db.models import Exists, OuterRef, Q
        _purge_expired_reservations()
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get('library'):
            qs = qs.filter(library_id=params['library'])
        if params.get('section'):
            qs = qs.filter(section_id=params['section'])
        if params.get('author'):
            qs = qs.filter(author_id=params['author'])
        # ebook filter: has_ebook=true | ebook_only=1
        if params.get('has_ebook') in ('true', '1') or params.get('ebook_only') in ('true', '1'):
            qs = qs.exclude(ebook_file='').exclude(ebook_file__isnull=True)
        # status filter: available | busy
        now = timezone.now()
        active_res = Reservation.objects.filter(book=OuterRef('pk'), expires_at__gt=now)
        active_iss = Issue.objects.filter(book=OuterRef('pk'), is_returned=False)
        status_param = (params.get('status') or params.get('is_available') or '').lower()
        if status_param in ('available', 'true', '1'):
            qs = qs.annotate(
                _iss=Exists(active_iss),
                _res=Exists(active_res),
            ).filter(_iss=False, _res=False)
        elif status_param in ('busy', 'reserved', 'issued', 'false', '0'):
            qs = qs.annotate(
                _iss=Exists(active_iss),
                _res=Exists(active_res),
            ).filter(Q(_iss=True) | Q(_res=True))
        return qs

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        Book.objects.filter(pk=instance.pk).update(view_count=F('view_count') + 1)
        instance.refresh_from_db(fields=['view_count'])
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='popular', permission_classes=[AllowAny])
    def popular(self, request):
        try:
            limit = int(request.query_params.get('limit', 10))
        except ValueError:
            limit = 10
        books = Book.objects.all().order_by('-view_count', '-issue_count', '-reservation_count')[:limit]
        return Response(self.get_serializer(books, many=True).data)

    @action(detail=False, methods=['get'], url_path='top-rated', permission_classes=[AllowAny])
    def top_rated(self, request):
        try:
            limit = int(request.query_params.get('limit', 10))
        except ValueError:
            limit = 10
        books = Book.objects.annotate(
            avg=Avg('ratings__rating'), cnt=Count('ratings')
        ).filter(cnt__gt=0).order_by('-avg', '-cnt')[:limit]
        return Response(self.get_serializer(books, many=True).data)

    @action(detail=False, methods=['get'], url_path='most-read', permission_classes=[AllowAny])
    def most_read(self, request):
        try:
            limit = int(request.query_params.get('limit', 10))
        except ValueError:
            limit = 10
        books = Book.objects.all().order_by('-issue_count', '-view_count')[:limit]
        return Response(self.get_serializer(books, many=True).data)

    @action(detail=False, methods=['get'], url_path='recommended-for-me', permission_classes=[AllowAny])
    def recommended_for_me(self, request):
        """Foydalanuvchining tarixiga (issues + reservations + favourites) qarab tavsiya."""
        from django.db.models import Q
        try:
            limit = int(request.query_params.get('limit', 8))
        except ValueError:
            limit = 8

        reader = _resolve_reader_by_token(request)
        if reader is None:
            # Mehmon — eng mashhurlarni qaytaramiz
            books = Book.objects.all().order_by('-view_count', '-issue_count')[:limit]
            return Response(self.get_serializer(books, many=True, context={'request': request}).data)

        # Foydalanuvchi tarixi
        history_ids = set()
        history_ids.update(Issue.objects.filter(reader=reader).values_list('book_id', flat=True))
        history_ids.update(Reservation.objects.filter(reader=reader).values_list('book_id', flat=True))
        history_ids.update(BookFavourite.objects.filter(reader=reader).values_list('book_id', flat=True))

        if not history_ids:
            books = Book.objects.all().order_by('-view_count', '-issue_count')[:limit]
            return Response(self.get_serializer(books, many=True, context={'request': request}).data)

        history_books = Book.objects.filter(id__in=history_ids).select_related('section', 'author')
        section_ids = {b.section_id for b in history_books if b.section_id}
        author_ids  = {b.author_id  for b in history_books if b.author_id}

        if not section_ids and not author_ids:
            books = Book.objects.exclude(id__in=history_ids).order_by('-view_count')[:limit]
            return Response(self.get_serializer(books, many=True, context={'request': request}).data)

        flt = Q()
        if section_ids: flt |= Q(section_id__in=section_ids)
        if author_ids:  flt |= Q(author_id__in=author_ids)

        books = (Book.objects.filter(flt)
                 .exclude(id__in=history_ids)
                 .order_by('-view_count', '-issue_count')[:limit])
        return Response(self.get_serializer(books, many=True, context={'request': request}).data)

    @action(detail=False, methods=['get'], url_path='autocomplete', permission_classes=[AllowAny])
    def autocomplete(self, request):
        """Qidiruv autocomplete — kitob nomi bo'yicha tezkor takliflar."""
        from django.db.models import Q
        q = (request.query_params.get('q') or '').strip()
        if len(q) < 2:
            return Response([])
        try:
            limit = int(request.query_params.get('limit', 8))
        except ValueError:
            limit = 8
        books = (Book.objects
                 .filter(Q(title__icontains=q) | Q(author__first_name__icontains=q) | Q(author__last_name__icontains=q))
                 .select_related('author', 'library')
                 .order_by('-view_count')[:limit])
        return Response([
            {
                'id': b.id,
                'title': b.title,
                'author': str(b.author) if b.author else '',
                'library': b.library.name if b.library else '',
                'cover': b.cover_image.url if b.cover_image else '',
            }
            for b in books
        ])

    @action(detail=False, methods=['get'], url_path='trending', permission_classes=[AllowAny])
    def trending(self, request):
        try:
            limit = int(request.query_params.get('limit', 10))
        except ValueError:
            limit = 10
        books = Book.objects.all().order_by('-reservation_count', '-view_count')[:limit]
        return Response(self.get_serializer(books, many=True).data)

    @action(detail=True, methods=['post'], url_path='upload-cover')
    def upload_cover(self, request, pk=None):
        book = self.get_object()
        file = request.FILES.get('file')
        if file:
            book.cover_image = file
            book.save()
            return Response({'status': 'Image uploaded', 'url': book.cover_image.url})
        return Response({'error': 'No file provided'}, status=400)

    @action(detail=True, methods=['post'], url_path='upload-ebook')
    def upload_ebook(self, request, pk=None):
        book = self.get_object()
        file = request.FILES.get('file')
        if file:
            book.ebook_file = file
            book.save()
            return Response({'status': 'Ebook uploaded', 'url': book.ebook_file.url})
        return Response({'error': 'No file provided'}, status=400)

    @action(detail=True, methods=['post', 'put'], url_path='rate', permission_classes=[AllowAny])
    def rate(self, request, pk=None):
        reader = _resolve_reader_by_token(request)
        if reader is None:
            return Response({'detail': 'Invalid or missing reader token.'}, status=status.HTTP_401_UNAUTHORIZED)

        book = self.get_object()
        rating_value = request.data.get('rating')
        review = request.data.get('review', '') or ''
        try:
            rating_int = int(rating_value)
        except (TypeError, ValueError):
            return Response({'rating': 'Rating must be an integer 1..5.'}, status=status.HTTP_400_BAD_REQUEST)
        if rating_int < 1 or rating_int > 5:
            return Response({'rating': 'Rating must be 1..5.'}, status=status.HTTP_400_BAD_REQUEST)

        rating_obj, _created = BookRating.objects.update_or_create(
            reader=reader, book=book,
            defaults={'rating': rating_int, 'review': review},
        )
        return Response(BookRatingSerializer(rating_obj).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='ratings', permission_classes=[AllowAny])
    def ratings(self, request, pk=None):
        book = self.get_object()
        qs = book.ratings.all().order_by('-updated_at')
        return Response(BookRatingSerializer(qs, many=True).data)


class ReaderViewSet(viewsets.ModelViewSet):
    queryset = Reader.objects.all()
    serializer_class = ReaderSerializer

    def get_permissions(self):
        if self.action in ['register', 'login', 'me', 'library_cards', 'refresh_status', 'check_library_card', 'my_stats', 'update_me']:
            return [AllowAny()]
        return [IsAdminTokenOrReadOnly()]

    @action(detail=False, methods=['post'], url_path='register')
    def register(self, request):
        serializer = ReaderRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reader = serializer.save()
        return Response(
            {
                'id': reader.id,
                'fullname': reader.fullname,
                'card_id': reader.card_id,
                'message': 'Registration successful.',
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['post'], url_path='login')
    def login(self, request):
        serializer = ReaderLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'detail': 'Login failed. Check phone/card ID and password.', 'errors': serializer.errors},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        reader = serializer.validated_data['reader']

        reader.session_token = secrets.token_urlsafe(32)
        reader.token_created_at = timezone.now()
        reader.save(update_fields=['session_token', 'token_created_at'])

        return Response(
            {
                'token': reader.session_token,
                'reader': ReaderSerializer(reader).data,
                'id': reader.id,
                'fullname': reader.fullname,
                'card_id': reader.card_id,
            }
        )

    @action(detail=False, methods=['get'], url_path='me')
    def me(self, request):
        reader = _resolve_reader_by_token(request)
        if reader is None:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(ReaderSerializer(reader).data)

    @action(detail=False, methods=['put', 'patch'], url_path='update-me', permission_classes=[AllowAny])
    def update_me(self, request):
        reader = _resolve_reader_by_token(request)
        if reader is None:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_401_UNAUTHORIZED)

        fullname = request.data.get('fullname')
        phone = request.data.get('phone')
        email = request.data.get('email')
        password = request.data.get('password')
        notify_email = request.data.get('notify_email')

        if fullname:
            reader.fullname = fullname
        if phone:
            reader.phone = phone
        if email is not None:
            reader.email = email
        if notify_email is not None:
            if isinstance(notify_email, str):
                reader.notify_email = notify_email.lower() in ('1', 'true', 'on', 'yes')
            else:
                reader.notify_email = bool(notify_email)
        if password:
            from django.contrib.auth.hashers import make_password
            reader.password_hash = make_password(password)

        reader.save()
        return Response({
            'detail': 'Profile updated successfully.',
            'reader': ReaderSerializer(reader).data
        })

    @action(detail=False, methods=['get'], url_path='my-stats', permission_classes=[AllowAny])
    def my_stats(self, request):
        """O'quvchining gamification statistikasi: ko'rsatkichlar va belgilar."""
        reader = _resolve_reader_by_token(request)
        if reader is None:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_401_UNAUTHORIZED)

        from datetime import timedelta
        now = timezone.now()
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_30_days = now - timedelta(days=30)

        total_issues       = Issue.objects.filter(reader=reader).count()
        returned_issues    = Issue.objects.filter(reader=reader, is_returned=True).count()
        active_issues      = Issue.objects.filter(reader=reader, is_returned=False).count()
        month_issues       = Issue.objects.filter(reader=reader, issue_date__gte=start_of_month.date()).count()
        recent_issues      = Issue.objects.filter(reader=reader, issue_date__gte=last_30_days.date()).count()
        total_reservations = Reservation.objects.filter(reader=reader).count()
        active_reservations= Reservation.objects.filter(reader=reader, expires_at__gt=now).count()
        total_favourites   = BookFavourite.objects.filter(reader=reader).count()
        total_ratings      = BookRating.objects.filter(reader=reader).count()

        # Belgilar (badges)
        badges = []
        if total_issues >= 1:
            badges.append({'code': 'first_book',   'name': 'Birinchi kitob',  'icon': '📖', 'description': 'Birinchi kitob olindi'})
        if total_issues >= 10:
            badges.append({'code': 'reader_10',    'name': "O'qiganchi",      'icon': '📚', 'description': '10 kitob o\'qildi'})
        if total_issues >= 50:
            badges.append({'code': 'bibliophile',  'name': 'Bibliofil',       'icon': '🎓', 'description': '50 kitob o\'qildi'})
        if total_issues >= 100:
            badges.append({'code': 'sage',         'name': 'Donishmand',      'icon': '👑', 'description': '100 kitob o\'qildi'})
        if total_ratings >= 1:
            badges.append({'code': 'first_review', 'name': 'Ilk sharh',       'icon': '⭐', 'description': 'Birinchi sharh yozildi'})
        if total_ratings >= 10:
            badges.append({'code': 'critic',       'name': 'Tanqidchi',       'icon': '🖋',  'description': '10 ta sharh yozildi'})
        if total_favourites >= 5:
            badges.append({'code': 'collector',    'name': 'Yig\'uvchi',      'icon': '❤️', 'description': '5 sevimli kitob'})
        if month_issues >= 5:
            badges.append({'code': 'active_month', 'name': 'Faol oy',         'icon': '🔥', 'description': 'Bu oyda 5+ kitob'})
        if returned_issues >= 1 and active_issues == 0 and total_issues >= 3:
            badges.append({'code': 'punctual',     'name': 'Aniq vaqtli',     'icon': '⏰', 'description': 'Hamma kitoblar qaytarilgan'})

        # Daraja: 0–9 = Yangi, 10–24 = O'qiganchi, 25–49 = Mutolaachi, 50–99 = Bibliofil, 100+ = Donishmand
        if total_issues >= 100:
            level = {'name': 'Donishmand', 'tier': 5, 'next_at': None}
        elif total_issues >= 50:
            level = {'name': 'Bibliofil',  'tier': 4, 'next_at': 100}
        elif total_issues >= 25:
            level = {'name': 'Mutolaachi', 'tier': 3, 'next_at': 50}
        elif total_issues >= 10:
            level = {'name': "O'qiganchi", 'tier': 2, 'next_at': 25}
        else:
            level = {'name': 'Yangi',      'tier': 1, 'next_at': 10}

        return Response({
            'level': level,
            'badges': badges,
            'metrics': {
                'total_issues':        total_issues,
                'returned_issues':     returned_issues,
                'active_issues':       active_issues,
                'month_issues':        month_issues,
                'recent_issues':       recent_issues,
                'total_reservations':  total_reservations,
                'active_reservations': active_reservations,
                'total_favourites':    total_favourites,
                'total_ratings':       total_ratings,
            },
        })

    @action(detail=False, methods=['get'], url_path='refresh-status')
    def refresh_status(self, request):
        reader = _resolve_reader_by_token(request)
        if reader is None:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_401_UNAUTHORIZED)
        return Response({
            'id': reader.id,
            'is_active': reader.is_active,
            'fullname': reader.fullname,
            'card_id': reader.card_id,
        })

    @action(detail=False, methods=['get', 'post'], url_path='library-cards')
    def library_cards(self, request):
        reader = _resolve_reader_by_token(request)
        if reader is None:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_401_UNAUTHORIZED)

        if request.method == 'GET':
            cards = ReaderLibraryCard.objects.filter(reader=reader).select_related('library').order_by('-updated_at')
            return Response(ReaderLibraryCardSerializer(cards, many=True).data)

        library_id = request.data.get('library')
        card_image_base64 = request.data.get('card_image_base64', '')

        if not library_id:
            return Response({'library': 'Library id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        library = Library.objects.filter(pk=library_id).first()
        if library is None:
            return Response({'library': 'Library not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Karta mavjud va tasdiqlangan bo'lsa — rasm so'ramaymiz
        existing_card = ReaderLibraryCard.objects.filter(reader=reader, library=library).first()
        if existing_card is not None and existing_card.is_approved:
            return Response(ReaderLibraryCardSerializer(existing_card).data, status=status.HTTP_200_OK)

        if not card_image_base64:
            return Response({'card_image_base64': 'Card image is required.'}, status=status.HTTP_400_BAD_REQUEST)

        cleaned_b64 = card_image_base64
        if ';base64,' in cleaned_b64:
            cleaned_b64 = cleaned_b64.split(';base64,', 1)[1]

        try:
            file_bytes = base64.b64decode(cleaned_b64)
        except Exception:
            return Response({'card_image_base64': 'Invalid base64 image.'}, status=status.HTTP_400_BAD_REQUEST)

        if existing_card is not None:
            # Karta bor lekin tasdiqlanmagan — yangi rasm bilan yangilaymiz
            card = existing_card
            card.is_approved = False
        else:
            card = ReaderLibraryCard(reader=reader, library=library)
        filename = f"library_card_{uuid.uuid4().hex}.jpg"
        card.card_image.save(filename, ContentFile(file_bytes), save=False)
        card.save()

        return Response(ReaderLibraryCardSerializer(card).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='check-library-card')
    def check_library_card(self, request):
        """Reader o'z kartasining holatini tekshiradi (ma'lum kutubxona uchun)"""
        reader = _resolve_reader_by_token(request)
        if reader is None:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_401_UNAUTHORIZED)

        library_id = request.query_params.get('library')
        if not library_id:
            return Response({'library': 'Library id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        card = ReaderLibraryCard.objects.filter(reader=reader, library_id=library_id).first()
        if card is None:
            return Response({'has_card': False, 'is_approved': False})
        return Response({
            'has_card': True,
            'is_approved': card.is_approved,
            'card': ReaderLibraryCardSerializer(card).data,
        })


class IssueViewSet(viewsets.ModelViewSet):
    queryset = Issue.objects.all()
    serializer_class = IssueSerializer
    permission_classes = [IsAdminTokenOrReadOnly]

    def get_queryset(self):
        qs = Issue.objects.all().select_related('reader', 'book').order_by('-issue_date')
        if self.request.query_params.get('mine') == '1':
            reader = _resolve_reader_by_token(self.request)
            if reader is not None:
                qs = qs.filter(reader=reader)
            else:
                qs = qs.none()
        reader_id = self.request.query_params.get('reader')
        if reader_id:
            qs = qs.filter(reader_id=reader_id)
        return qs

    def create(self, request, *args, **kwargs):
        _purge_expired_reservations()
        book_id = request.data.get('book')
        if book_id:
            if Issue.objects.filter(book_id=book_id, is_returned=False).exists():
                return Response(
                    {'detail': "Bu kitob hozirda boshqa o'quvchiga berilgan va qaytarilmagan."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            now = timezone.now()
            active_res = Reservation.objects.filter(book_id=book_id, expires_at__gt=now)
            if active_res.exists():
                reader_id = request.data.get('reader')
                if not active_res.filter(reader_id=reader_id).exists():
                    return Response(
                        {'detail': "Bu kitob boshqa o'quvchi tomonidan band qilingan."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
        response = super().create(request, *args, **kwargs)
        if response.status_code in (200, 201) and book_id:
            # Kitob berilgach barcha bronlarni o'chiramiz
            Reservation.objects.filter(book_id=book_id).delete()
        return response

    def perform_create(self, serializer):
        issue = serializer.save()
        Book.objects.filter(pk=issue.book_id).update(issue_count=F('issue_count') + 1)

    @action(detail=True, methods=['post'], url_path='return')
    def return_book(self, request, pk=None):
        issue = self.get_object()
        if issue.is_returned:
            return Response({'detail': 'Bu kitob allaqachon qaytarilgan.'}, status=status.HTTP_400_BAD_REQUEST)
        issue.is_returned = True
        issue.save(update_fields=['is_returned'])
        return Response({
            'id': issue.id,
            'is_returned': True,
            'book_title': issue.book.title,
            'reader_name': issue.reader.fullname,
        })


class ReservationViewSet(viewsets.ModelViewSet):
    queryset = Reservation.objects.all()
    serializer_class = ReservationSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        _purge_expired_reservations()
        qs = Reservation.objects.all().select_related('reader', 'book').order_by('-reserved_at')
        if self.request.query_params.get('mine') == '1':
            reader = _resolve_reader_by_token(self.request)
            if reader is not None:
                qs = qs.filter(reader=reader)
            else:
                qs = qs.none()
        return qs

    def create(self, request, *args, **kwargs):
        _purge_expired_reservations()

        reader = _resolve_reader_by_token(request)
        if reader is None:
            return Response(
                {'detail': "Tizimga kirishingiz kerak. Iltimos, qayta kiring."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        book_id = request.data.get('book')
        if not book_id:
            return Response({'detail': "Kitob tanlanmagan."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            book = Book.objects.select_related('library').get(pk=book_id)
        except Book.DoesNotExist:
            return Response({'detail': "Kitob topilmadi."}, status=status.HTTP_404_NOT_FOUND)

        if Issue.objects.filter(book=book, is_returned=False).exists():
            return Response(
                {'detail': "Bu kitob hozirda biror o'quvchiga berilgan va bronlab bo'lmaydi."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        now = timezone.now()
        if Reservation.objects.filter(book=book, expires_at__gt=now).exists():
            return Response(
                {'detail': "Bu kitob allaqachon band qilingan."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if book.library:
            card = ReaderLibraryCard.objects.filter(reader=reader, library=book.library).first()
            if card is None:
                return Response(
                    {'detail': f"'{book.library.name}' kutubxonasi uchun ruxsatnoma kartasi kerak. Profil sahifasidan yuklang."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not card.is_approved:
                return Response(
                    {'detail': "Kutubxona kartangiz admin tomonidan hali tasdiqlanmagan. Tasdiq kutilmoqda."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            reservation = Reservation.objects.create(reader=reader, book=book)
        except Exception:
            return Response(
                {'detail': "Bronlashda xato yuz berdi. Kitob allaqachon band bo'lishi mumkin."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        Book.objects.filter(pk=book.pk).update(reservation_count=F('reservation_count') + 1)
        return Response(
            {
                'id': reservation.id,
                'book': book.id,
                'book_title': book.title,
                'expires_at': reservation.expires_at.isoformat() if reservation.expires_at else None,
                'days_remaining': reservation.days_remaining,
            },
            status=status.HTTP_201_CREATED,
        )

    def perform_create(self, serializer):
        reservation = serializer.save()
        Book.objects.filter(pk=reservation.book_id).update(reservation_count=F('reservation_count') + 1)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        reader = _resolve_reader_by_token(request)
        if not _is_admin_request(request) and (reader is None or reader.id != instance.reader_id):
            return Response({'detail': 'Not allowed.'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class BookRatingViewSet(viewsets.ModelViewSet):
    queryset = BookRating.objects.all().select_related('reader', 'book')
    serializer_class = BookRatingSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = super().get_queryset().order_by('-updated_at')
        book_id = self.request.query_params.get('book')
        if book_id:
            qs = qs.filter(book_id=book_id)
        if self.request.query_params.get('mine') == '1':
            reader = _resolve_reader_by_token(self.request)
            if reader is not None:
                qs = qs.filter(reader=reader)
            else:
                qs = qs.none()
        return qs

    def perform_create(self, serializer):
        reader = _resolve_reader_by_token(self.request)
        if reader is None:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Authentication token required.')
        book = serializer.validated_data['book']
        rating = serializer.validated_data['rating']
        review = serializer.validated_data.get('review', '') or ''
        BookRating.objects.update_or_create(
            reader=reader, book=book,
            defaults={'rating': rating, 'review': review},
        )


class BookFavouriteViewSet(viewsets.ModelViewSet):
    """Foydalanuvchining sevimli kitoblari — har o'quvchi uchun alohida."""
    queryset = BookFavourite.objects.all()
    serializer_class = BookFavouriteSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        reader = _resolve_reader_by_token(self.request)
        if reader is None:
            return BookFavourite.objects.none()
        return BookFavourite.objects.filter(reader=reader).select_related(
            'book', 'book__library', 'book__author'
        )

    def create(self, request, *args, **kwargs):
        reader = _resolve_reader_by_token(request)
        if reader is None:
            return Response({'detail': 'Tizimga kiring.'}, status=status.HTTP_401_UNAUTHORIZED)
        book_id = request.data.get('book')
        if not book_id:
            return Response({'detail': 'Kitob tanlanmagan.'}, status=status.HTTP_400_BAD_REQUEST)
        if not Book.objects.filter(pk=book_id).exists():
            return Response({'detail': 'Kitob topilmadi.'}, status=status.HTTP_404_NOT_FOUND)
        fav, created = BookFavourite.objects.get_or_create(reader=reader, book_id=book_id)
        return Response(
            BookFavouriteSerializer(fav).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def destroy(self, request, *args, **kwargs):
        reader = _resolve_reader_by_token(request)
        if reader is None:
            return Response({'detail': 'Tizimga kiring.'}, status=status.HTTP_401_UNAUTHORIZED)
        instance = self.get_object()
        if instance.reader_id != reader.id:
            return Response({'detail': 'Ruxsat yo\'q.'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['post'], url_path='toggle', permission_classes=[AllowAny])
    def toggle(self, request):
        """Sevimliga qo'shish/o'chirish (bitta endpoint)."""
        reader = _resolve_reader_by_token(request)
        if reader is None:
            return Response({'detail': 'Tizimga kiring.'}, status=status.HTTP_401_UNAUTHORIZED)
        book_id = request.data.get('book')
        if not book_id:
            return Response({'detail': 'Kitob tanlanmagan.'}, status=status.HTTP_400_BAD_REQUEST)
        if not Book.objects.filter(pk=book_id).exists():
            return Response({'detail': 'Kitob topilmadi.'}, status=status.HTTP_404_NOT_FOUND)
        existing = BookFavourite.objects.filter(reader=reader, book_id=book_id).first()
        if existing:
            existing.delete()
            return Response({'is_favourite': False, 'book': int(book_id)})
        BookFavourite.objects.create(reader=reader, book_id=book_id)
        return Response({'is_favourite': True, 'book': int(book_id)}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='ids', permission_classes=[AllowAny])
    def ids(self, request):
        """Faqat sevimli kitoblar IDsi — Index sahifasi uchun (yengil)."""
        reader = _resolve_reader_by_token(request)
        if reader is None:
            return Response([])
        ids = list(BookFavourite.objects.filter(reader=reader).values_list('book_id', flat=True))
        return Response(ids)


class ReaderLibraryCardAdminViewSet(viewsets.ModelViewSet):
    """
    Admin C++ dasturi orqali Kutubxona Kartalarini ro'yxatdan o'tkazish,
    ko'rish va tasdiqlash uchun maxsus endpoint.
    """
    queryset = ReaderLibraryCard.objects.all().select_related('reader', 'library').order_by('-created_at')
    serializer_class = ReaderLibraryCardSerializer
    permission_classes = [IsAdminTokenOrReadOnly]

    def list(self, request, *args, **kwargs):
        # Admin C++ dasturiga oson formatda jo'natamiz
        cards = self.get_queryset()
        data = []
        for card in cards:
            data.append({
                'id': card.id,
                'reader_id': card.reader.id,
                'reader_name': card.reader.fullname,
                'reader_card_id': card.reader.card_id,
                'reader_phone': card.reader.phone,
                'library_name': card.library.name,
                'card_image': card.card_image.url if card.card_image else 'null',
                'is_approved': card.is_approved,
                'created_at': card.created_at.isoformat(),
            })
        return Response(data)

    def update(self, request, *args, **kwargs):
        # Faqat is_approved o'zgartirish uchun
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        if 'is_approved' in request.data:
            instance.is_approved = request.data['is_approved']
            instance.save(update_fields=['is_approved'])
            return Response({'id': instance.id, 'is_approved': instance.is_approved})
        return super().update(request, *args, **kwargs)


class AIAdvisorViewSet(viewsets.ViewSet):
    """Gemini 2.5 Flash asosida ishlovchi AI maslahatchi."""
    permission_classes = [AllowAny]

    @action(detail=False, methods=['get'], url_path='status')
    def status_check(self, request):
        from . import ai_service
        return Response({'configured': ai_service.is_configured()})

    @action(detail=False, methods=['post'], url_path='chat')
    def chat(self, request):
        from . import ai_service
        message = (request.data.get('message') or '').strip()
        history = request.data.get('history') or []
        if not isinstance(history, list):
            history = []
        if not message:
            return Response({'error': 'Xabar bo\'sh.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(message) > 1500:
            return Response({'error': 'Xabar juda uzun (max 1500 belgi).'}, status=status.HTTP_400_BAD_REQUEST)

        # Tarixdan keyingi 8 ta xabarni olamiz
        clean_history = []
        for m in history[-8:]:
            if isinstance(m, dict) and m.get('content'):
                role = m.get('role')
                clean_history.append({
                    'role': 'model' if role == 'model' else 'user',
                    'content': str(m.get('content'))[:1500],
                })

        # Kitoblar katalogi (kontekst uchun)
        catalog = list(
            Book.objects.select_related('author', 'library')
            .order_by('-view_count', '-issue_count')[:60]
        )
        catalog_payload = [
            {
                'id': b.id,
                'title': b.title,
                'author': str(b.author) if b.author else '',
                'library': b.library.name if b.library else '',
            }
            for b in catalog
        ]

        result = ai_service.chat(
            user_message=message,
            history=clean_history,
            book_catalog=catalog_payload,
        )
        if 'error' in result:
            return Response({'error': result['error']}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({'reply': result.get('reply', '')})

