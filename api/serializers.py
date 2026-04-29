import base64
import uuid
from datetime import timedelta

from django.core.files.base import ContentFile
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password
from rest_framework import serializers
from .models import Library, Section, Author, Book, Reader, Issue, Reservation, ReaderLibraryCard

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
    library_latitude = serializers.FloatField(source='library.latitude', read_only=True, default=0)
    library_longitude = serializers.FloatField(source='library.longitude', read_only=True, default=0)
    section_name = serializers.CharField(source='section.name', read_only=True, default='')

    class Meta:
        model = Book
        fields = '__all__'

    def get_author_name(self, obj):
        return str(obj.author) if obj.author else ''

class ReaderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reader
        fields = ['id', 'fullname', 'phone', 'card_id', 'card_image', 'is_approved', 'is_active', 'created_at']
        read_only_fields = ['is_approved', 'is_active', 'created_at']


class ReaderRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    card_image_base64 = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Reader
        fields = ['fullname', 'phone', 'card_id', 'password', 'card_image_base64']

    def create(self, validated_data):
        password = validated_data.pop('password')
        image_b64 = validated_data.pop('card_image_base64', '')
        reader = Reader(**validated_data)
        reader.password_hash = make_password(password)
        reader.is_approved = False
        reader.is_active = True

        if image_b64:
            if ';base64,' in image_b64:
                image_b64 = image_b64.split(';base64,', 1)[1]
            file_bytes = base64.b64decode(image_b64)
            filename = f"reader_{uuid.uuid4().hex}.jpg"
            reader.card_image.save(filename, ContentFile(file_bytes), save=False)

        reader.save()
        return reader


class ReaderLoginSerializer(serializers.Serializer):
    card_id = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        card_id = attrs.get('card_id')
        password = attrs.get('password')
        try:
            reader = Reader.objects.get(card_id=card_id)
        except Reader.DoesNotExist as exc:
            raise serializers.ValidationError({'card_id': 'Reader not found.'}) from exc

        if not reader.is_active:
            raise serializers.ValidationError({'detail': 'Account is inactive.'})

        if not check_password(password, reader.password_hash):
            raise serializers.ValidationError({'password': 'Invalid credentials.'})

        attrs['reader'] = reader
        return attrs

class IssueSerializer(serializers.ModelSerializer):
    reader_name = serializers.CharField(source='reader.fullname', read_only=True)
    book_title = serializers.CharField(source='book.title', read_only=True)

    class Meta:
        model = Issue
        fields = '__all__'


class ReservationSerializer(serializers.ModelSerializer):
    reader_name = serializers.CharField(source='reader.fullname', read_only=True)
    book_title = serializers.CharField(source='book.title', read_only=True)
    library_card_image_base64 = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Reservation
        fields = '__all__'

    def validate(self, attrs):
        request = self.context.get('request')
        reader = attrs.get('reader')
        book = attrs.get('book')
        card_image_base64 = attrs.pop('library_card_image_base64', '')

        if request is None or reader is None:
            raise serializers.ValidationError({'detail': 'Invalid reservation request.'})

        token = request.headers.get('X-Reader-Token')
        if not token:
            auth_header = request.headers.get('Authorization', '')
            if auth_header.lower().startswith('bearer '):
                token = auth_header[7:].strip()

        if not token:
            raise serializers.ValidationError({'detail': 'Authentication token is required.'})

        if reader.session_token != token:
            raise serializers.ValidationError({'detail': 'Invalid reader token.'})

        if not reader.token_created_at or timezone.now() - reader.token_created_at > timedelta(hours=24):
            raise serializers.ValidationError({'detail': 'Session expired. Please login again.'})

        if not reader.is_approved:
            raise serializers.ValidationError({'detail': 'Reader account is not approved by admin yet.'})

        if book and Issue.objects.filter(book=book).exists():
            raise serializers.ValidationError({'book': 'This book is currently issued and cannot be reserved.'})
        if book and Reservation.objects.filter(book=book).exists():
            raise serializers.ValidationError({'book': 'This book is already reserved.'})

        if book is None or book.library is None:
            raise serializers.ValidationError({'book': 'Book is not linked to a valid library.'})

        existing_card = ReaderLibraryCard.objects.filter(reader=reader, library=book.library).first()
        if existing_card is None:
            if not card_image_base64:
                raise serializers.ValidationError({
                    'library_card_image_base64': 'Library card image is required for this library.'
                })

            cleaned_b64 = card_image_base64
            if ';base64,' in cleaned_b64:
                cleaned_b64 = cleaned_b64.split(';base64,', 1)[1]

            try:
                file_bytes = base64.b64decode(cleaned_b64)
            except Exception as exc:
                raise serializers.ValidationError({'library_card_image_base64': 'Invalid base64 image.'}) from exc

            filename = f"library_card_{uuid.uuid4().hex}.jpg"
            card = ReaderLibraryCard(reader=reader, library=book.library)
            card.card_image.save(filename, ContentFile(file_bytes), save=False)
            card.save()

        return attrs


class ReaderLibraryCardSerializer(serializers.ModelSerializer):
    library_name = serializers.CharField(source='library.name', read_only=True)

    class Meta:
        model = ReaderLibraryCard
        fields = ['id', 'reader', 'library', 'library_name', 'card_image', 'created_at', 'updated_at']
        read_only_fields = ['id', 'reader', 'library_name', 'created_at', 'updated_at']
