from django.contrib import admin
from .models import Library, Section, Author, Book, Reader, Issue, Reservation, ReaderLibraryCard, BookRating

admin.site.register([Library, Section, Author, Book, Issue, Reservation, ReaderLibraryCard, BookRating])


@admin.register(Reader)
class ReaderAdmin(admin.ModelAdmin):
    list_display = ('id', 'fullname', 'phone', 'card_id', 'is_approved', 'is_active', 'created_at')
    list_filter = ('is_approved', 'is_active', 'created_at')
    search_fields = ('fullname', 'phone', 'card_id')
