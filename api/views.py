from rest_framework import viewsets
from .models import Library, Section, Author, Book, Reader, Issue
from .serializers import LibrarySerializer, SectionSerializer, AuthorSerializer, BookSerializer, ReaderSerializer, IssueSerializer

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

class IssueViewSet(viewsets.ModelViewSet):
    queryset = Issue.objects.all()
    serializer_class = IssueSerializer
