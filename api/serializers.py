from rest_framework import serializers
from .models import Library, Section, Author, Book, Reader, Issue

class LibrarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Library
        fields = '__all__'

class SectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Section
        fields = '__all__'

class AuthorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Author
        fields = '__all__'

class BookSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    library_name = serializers.CharField(source='library.name', read_only=True, default='')
    section_name = serializers.CharField(source='section.name', read_only=True, default='')

    class Meta:
        model = Book
        fields = '__all__'

    def get_author_name(self, obj):
        return str(obj.author) if obj.author else ''

class ReaderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reader
        fields = '__all__'

class IssueSerializer(serializers.ModelSerializer):
    reader_name = serializers.CharField(source='reader.fullname', read_only=True)
    book_title = serializers.CharField(source='book.title', read_only=True)

    class Meta:
        model = Issue
        fields = '__all__'
