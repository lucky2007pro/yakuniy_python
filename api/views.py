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
        if not reader.is_approved:
            return Response({'detail': 'Reader account is not approved.'}, status=status.HTTP_403_FORBIDDEN)

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
        if self.action in ['register', 'login', 'me', 'library_cards', 'refresh_status']:
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
                'is_approved': reader.is_approved,
                'message': 'Registration successful. Wait for admin approval.',
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
                'is_approved': reader.is_approved,
            }
        )

    @action(detail=False, methods=['get'], url_path='me')
    def me(self, request):
        reader = _resolve_reader_by_token(request)
        if reader is None:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(ReaderSerializer(reader).data)

    @action(detail=False, methods=['get'], url_path='refresh-status')
    def refresh_status(self, request):
        reader = _resolve_reader_by_token(request)
        if reader is None:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_401_UNAUTHORIZED)
        return Response({
            'id': reader.id,
            'is_approved': reader.is_approved,
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
        if not card_image_base64:
            return Response({'card_image_base64': 'Card image is required.'}, status=status.HTTP_400_BAD_REQUEST)

        library = Library.objects.filter(pk=library_id).first()
        if library is None:
            return Response({'library': 'Library not found.'}, status=status.HTTP_404_NOT_FOUND)

        cleaned_b64 = card_image_base64
        if ';base64,' in cleaned_b64:
            cleaned_b64 = cleaned_b64.split(';base64,', 1)[1]

        try:
            file_bytes = base64.b64decode(cleaned_b64)
        except Exception:
            return Response({'card_image_base64': 'Invalid base64 image.'}, status=status.HTTP_400_BAD_REQUEST)

        card, _ = ReaderLibraryCard.objects.get_or_create(reader=reader, library=library)
        filename = f"library_card_{uuid.uuid4().hex}.jpg"
        card.card_image.save(filename, ContentFile(file_bytes), save=False)
        card.save()

        return Response(ReaderLibraryCardSerializer(card).data, status=status.HTTP_200_OK)


class IssueViewSet(viewsets.ModelViewSet):
    queryset = Issue.objects.all()
    serializer_class = IssueSerializer
    permission_classes = [IsAdminTokenOrReadOnly]

    def perform_create(self, serializer):
        issue = serializer.save()
        Book.objects.filter(pk=issue.book_id).update(issue_count=F('issue_count') + 1)


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
