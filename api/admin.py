from django.contrib import admin
from .models import Library, Section, Author, Book, Reader, Issue, Reservation, ReaderLibraryCard, BookRating

admin.site.register([Library, Section, Author, Book, Issue, Reservation])


@admin.register(Reader)
class ReaderAdmin(admin.ModelAdmin):
    list_display = ('id', 'fullname', 'phone', 'card_id', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('fullname', 'phone', 'card_id')



@admin.register(ReaderLibraryCard)
class ReaderLibraryCardAdmin(admin.ModelAdmin):
    list_display = ('id', 'reader', 'library', 'is_approved', 'created_at', 'updated_at')
    list_filter = ('is_approved', 'library', 'created_at')
    search_fields = ('reader__fullname', 'reader__phone', 'library__name')
    readonly_fields = ('created_at', 'updated_at', 'card_image_preview')
    actions = ['approve_cards', 'disapprove_cards']

    def card_image_preview(self, obj):
        from django.utils.html import mark_safe
        if obj.card_image:
            return mark_safe(f'<img src="{obj.card_image.url}" style="max-height: 200px; border-radius: 5px;" />')
        return "Rasm yuklanmagan"
    card_image_preview.short_description = "Karta rasmi (Preview)"

    @admin.action(description='Tanlangan kutubxona kartalarini tasdiqlash')
    def approve_cards(self, request, queryset):
        queryset.update(is_approved=True)

    @admin.action(description='Tanlangan kutubxona kartalarining tasdig\'ini bekor qilish')
    def disapprove_cards(self, request, queryset):
        queryset.update(is_approved=False)


@admin.register(BookRating)
class BookRatingAdmin(admin.ModelAdmin):
    list_display = ('id', 'reader', 'book', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = ('reader__fullname', 'book__title')

