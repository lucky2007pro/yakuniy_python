import base64
import uuid
from datetime import timedelta
from math import radians, sin, cos, asin, sqrt

from django.core.files.base import ContentFile
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password
from rest_framework import serializers
from django.db.models import Avg, Count
from .models import Library, Section, Author, Book, Reader, Issue, Reservation, ReaderLibraryCard, BookRating, BookFavourite


def _haversine_km(lat1, lon1, lat2, lon2):
    """Haversine formulasi orqali ikki nuqta orasidagi masofa (km)."""
    try:
        lat1, lon1, lat2, lon2 = map(radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
    except (TypeError, ValueError):
        return None
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return round(6371 * 2 * asin(sqrt(a)), 2)

class LibrarySerializer(serializers.ModelSerializer):
    book_count = serializers.SerializerMethodField()

    class Meta:
        model = Library
        fields = '__all__'

    def get_book_count(self, obj):
        return obj.books.count()

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
    average_rating = serializers.SerializerMethodField()
    ratings_count = serializers.SerializerMethodField()
    is_available = serializers.SerializerMethodField()
    availability_status = serializers.SerializerMethodField()
    distance_km = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = '__all__'

    def get_author_name(self, obj):
        return str(obj.author) if obj.author else ''

    def get_average_rating(self, obj):
        agg = obj.ratings.aggregate(avg=Avg('rating'))
        return round(agg['avg'], 2) if agg['avg'] is not None else 0.0

    def get_ratings_count(self, obj):
        return obj.ratings.count()

    def get_availability_status(self, obj):
        if Issue.objects.filter(book=obj, is_returned=False).exists():
            return 'issued'
        now = timezone.now()
        if Reservation.objects.filter(book=obj, expires_at__gt=now).exists():
            return 'reserved'
        return 'available'

    def get_is_available(self, obj):
        return self.get_availability_status(obj) == 'available'

    def get_distance_km(self, obj):
        request = self.context.get('request')
        if request is None or obj.library is None:
            return None
        lat = request.query_params.get('user_lat') if hasattr(request, 'query_params') else None
        lon = request.query_params.get('user_lon') if hasattr(request, 'query_params') else None
        if not lat or not lon:
            return None
        if obj.library.latitude is None or obj.library.longitude is None:
            return None
        return _haversine_km(lat, lon, obj.library.latitude, obj.library.longitude)


class ReaderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reader
        fields = ['id', 'fullname', 'phone', 'card_id', 'is_active', 'created_at']
        read_only_fields = ['created_at']


class ReaderRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    card_id = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Reader
        fields = ['fullname', 'phone', 'card_id', 'password']

    def create(self, validated_data):
        password = validated_data.pop('password')
        # Agar card_id berilmagan bo'lsa, avtomatik UUID generatsiya qilish
        if not validated_data.get('card_id'):
            validated_data['card_id'] = f"LIB{uuid.uuid4().hex[:8].upper()}"
        reader = Reader(**validated_data)
        reader.password_hash = make_password(password)
        reader.is_active = True
        reader.save()
        return reader


class ReaderLoginSerializer(serializers.Serializer):
    card_id = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        card_id = attrs.get('card_id', '')
        phone = attrs.get('phone', '')
        password = attrs.get('password')

        reader = None
        if card_id:
            try:
                reader = Reader.objects.get(card_id=card_id)
            except Reader.DoesNotExist:
                pass
        if not reader and phone:
            try:
                reader = Reader.objects.get(phone=phone)
            except Reader.DoesNotExist:
                pass

        if not reader:
            raise serializers.ValidationError({'detail': 'Reader not found.'})

        if not reader.is_active:
            raise serializers.ValidationError({'detail': 'Account is inactive.'})

        if not check_password(password, reader.password_hash):
            raise serializers.ValidationError({'password': 'Invalid credentials.'})

        # Foydalanuvchi is_approved bo'lmasdan ham login qila oladi
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
    is_expired = serializers.BooleanField(read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)

    class Meta:
        model = Reservation
        fields = '__all__'
        read_only_fields = ['reserved_at', 'expires_at']

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

        # Foydalanuvchi is_approved bo'lmasdan ham bron qila oladi
        # (Faqat kutubxona kartasi admin tasdiqlangan bo'lishi kerak)

        now = timezone.now()
        if book and Issue.objects.filter(book=book, is_returned=False).exists():
            raise serializers.ValidationError({'book': 'This book is currently issued and cannot be reserved.'})
        if book and Reservation.objects.filter(book=book, expires_at__gt=now).exists():
            raise serializers.ValidationError({'book': 'This book is already reserved.'})

        if book is None or book.library is None:
            raise serializers.ValidationError({'book': 'Book is not linked to a valid library.'})

        existing_card = ReaderLibraryCard.objects.filter(reader=reader, library=book.library).first()

        if existing_card is not None and existing_card.is_approved:
            # Karta mavjud va admin tasdiqlagan — rasm so'ramaymiz
            pass
        else:
            # Karta yo'q yoki tasdiqlanmagan — yangi rasm kerak
            if not card_image_base64:
                if existing_card is not None and not existing_card.is_approved:
                    raise serializers.ValidationError({
                        'library_card_image_base64': 'Your library card is pending admin approval. You may upload a new card image.'
                    })
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
            if existing_card is None:
                card = ReaderLibraryCard(reader=reader, library=book.library)
            else:
                card = existing_card  # Qayta yuklash — tasdiqlanmagan karta yangilanadi
                card.is_approved = False  # Yangi rasm — qayta tasdiqlash kerak
            card.card_image.save(filename, ContentFile(file_bytes), save=False)
            card.save()

        return attrs


class ReaderLibraryCardSerializer(serializers.ModelSerializer):
    library_name = serializers.CharField(source='library.name', read_only=True)

    class Meta:
        model = ReaderLibraryCard
        fields = ['id', 'reader', 'library', 'library_name', 'card_image', 'is_approved', 'created_at', 'updated_at']
        read_only_fields = ['id', 'reader', 'library_name', 'is_approved', 'created_at', 'updated_at']


class BookRatingSerializer(serializers.ModelSerializer):
    reader_name = serializers.CharField(source='reader.fullname', read_only=True)
    book_title = serializers.CharField(source='book.title', read_only=True)

    class Meta:
        model = BookRating
        fields = ['id', 'reader', 'reader_name', 'book', 'book_title', 'rating', 'review', 'created_at', 'updated_at']
        read_only_fields = ['id', 'reader', 'reader_name', 'book_title', 'created_at', 'updated_at']

    def validate_rating(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError('Rating must be between 1 and 5.')
        return value


class BookFavouriteSerializer(serializers.ModelSerializer):
    book_title = serializers.CharField(source='book.title', read_only=True)
    book_cover = serializers.SerializerMethodField()
    author_name = serializers.SerializerMethodField()
    library_name = serializers.CharField(source='book.library.name', read_only=True, default='')
    is_available = serializers.SerializerMethodField()
    availability_status = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()

    class Meta:
        model = BookFavourite
        fields = [
            'id', 'book', 'book_title', 'book_cover', 'author_name',
            'library_name', 'is_available', 'availability_status',
            'average_rating', 'created_at',
        ]
        read_only_fields = ['id', 'reader', 'created_at']

    def get_book_cover(self, obj):
        if obj.book and obj.book.cover_image:
            try:
                return obj.book.cover_image.url
            except Exception:
                return ''
        return ''

    def get_author_name(self, obj):
        return str(obj.book.author) if (obj.book and obj.book.author) else ''

    def get_availability_status(self, obj):
        if Issue.objects.filter(book=obj.book, is_returned=False).exists():
            return 'issued'
        now = timezone.now()
        if Reservation.objects.filter(book=obj.book, expires_at__gt=now).exists():
            return 'reserved'
        return 'available'

    def get_is_available(self, obj):
        return self.get_availability_status(obj) == 'available'

    def get_average_rating(self, obj):
        agg = obj.book.ratings.aggregate(avg=Avg('rating'))
        return round(agg['avg'], 2) if agg['avg'] is not None else 0.0
