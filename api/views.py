import secrets
import base64
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Avg, Count, F
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

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
)
from .permissions import IsAdminTokenOrReadOnly
from .serializers import (
    LibrarySerializer,
    SectionSerializer,
    AuthorSerializer,
    BookSerializer,
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
    # Drogon frontend filtr/qidiruv/saralash uchun
    from rest_framework import filters as drf_filters
    filter_backends = [drf_filters.SearchFilter, drf_filters.OrderingFilter]
    search_fields = ['title', 'description', 'isbn', 'author__first_name', 'author__last_name']
    ordering_fields = ['title', 'view_count', 'reservation_count', 'issue_count', 'published_date']
    ordering = ['-view_count']

    def get_queryset(self):
        from django.utils import timezone as tz
        from django.db.models import Exists, OuterRef, Q
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
        status_param = (params.get('status') or params.get('is_available') or '').lower()
        if status_param in ('available', 'true', '1'):
            qs = qs.annotate(
                _iss=Exists(Issue.objects.filter(book=OuterRef('pk'), is_returned=False)),
                _res=Exists(Reservation.objects.filter(book=OuterRef('pk'))),
            ).filter(_iss=False, _res=False)
        elif status_param in ('busy', 'reserved', 'issued', 'false', '0'):
            qs = qs.annotate(
                _iss=Exists(Issue.objects.filter(book=OuterRef('pk'), is_returned=False)),
                _res=Exists(Reservation.objects.filter(book=OuterRef('pk'))),
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
        if self.action in ['register', 'login', 'me', 'library_cards', 'refresh_status', 'check_library_card']:
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
        password = request.data.get('password')

        if fullname:
            reader.fullname = fullname
        if phone:
            reader.phone = phone
        if password:
            from django.contrib.auth.hashers import make_password
            reader.password_hash = make_password(password)

        reader.save()
        return Response({
            'detail': 'Profile updated successfully.',
            'reader': ReaderSerializer(reader).data
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
        book_id = request.data.get('book')
        if book_id:
            if Issue.objects.filter(book_id=book_id, is_returned=False).exists():
                return Response(
                    {'detail': "Bu kitob hozirda boshqa o'quvchiga berilgan va qaytarilmagan."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if Reservation.objects.filter(book_id=book_id).exists():
                reader_id = request.data.get('reader')
                if not Reservation.objects.filter(book_id=book_id, reader_id=reader_id).exists():
                    return Response(
                        {'detail': "Bu kitob boshqa o'quvchi tomonidan band qilingan."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
        response = super().create(request, *args, **kwargs)
        if response.status_code in (200, 201) and book_id:
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
        qs = Reservation.objects.all().select_related('reader', 'book').order_by('-reserved_at')
        if self.request.query_params.get('mine') == '1':
            reader = _resolve_reader_by_token(self.request)
            if reader is not None:
                qs = qs.filter(reader=reader)
            else:
                qs = qs.none()
        return qs

    def create(self, request, *args, **kwargs):
        from django.utils import timezone as tz

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
        if Reservation.objects.filter(book=book).exists():
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
            {'id': reservation.id, 'book': book.id, 'book_title': book.title},
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

