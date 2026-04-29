import secrets
import base64
import uuid

from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAdminUser
from .models import Library, Section, Author, Book, Reader, Issue, Reservation, ReaderLibraryCard
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
)

class LibraryViewSet(viewsets.ModelViewSet):
    queryset = Library.objects.all()
    serializer_class = LibrarySerializer

class SectionViewSet(viewsets.ModelViewSet):
    queryset = Section.objects.all()
    serializer_class = SectionSerializer

class AuthorViewSet(viewsets.ModelViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer

from rest_framework.decorators import action
from rest_framework.response import Response

class BookViewSet(viewsets.ModelViewSet):
    queryset = Book.objects.all()
    serializer_class = BookSerializer

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


class ReaderViewSet(viewsets.ModelViewSet):
    queryset = Reader.objects.all()
    serializer_class = ReaderSerializer

    def get_permissions(self):
        if self.action in ['register', 'login', 'me', 'library_cards']:
            return [AllowAny()]
        return [IsAdminUser()]

    def _resolve_reader_by_token(self, request):
        token = request.headers.get('X-Reader-Token')
        if not token:
            auth_header = request.headers.get('Authorization', '')
            if auth_header.lower().startswith('bearer '):
                token = auth_header[7:].strip()

        if not token:
            return None

        return Reader.objects.filter(session_token=token).first()

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
        serializer.is_valid(raise_exception=True)
        reader = serializer.validated_data['reader']

        reader.session_token = secrets.token_urlsafe(32)
        reader.token_created_at = timezone.now()
        reader.save(update_fields=['session_token', 'token_created_at'])

        return Response(
            {
                'token': reader.session_token,
                'reader': ReaderSerializer(reader).data,
                'is_approved': reader.is_approved,
            }
        )

    @action(detail=False, methods=['get'], url_path='me')
    def me(self, request):
        reader = self._resolve_reader_by_token(request)
        if reader is None:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_401_UNAUTHORIZED)

        return Response(ReaderSerializer(reader).data)

    @action(detail=False, methods=['get', 'post'], url_path='library-cards')
    def library_cards(self, request):
        reader = self._resolve_reader_by_token(request)
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


class ReservationViewSet(viewsets.ModelViewSet):
    queryset = Reservation.objects.all()
    serializer_class = ReservationSerializer
