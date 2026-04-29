from django.db import models

class Library(models.Model):
    name = models.CharField(max_length=200)
    latitude = models.FloatField()
    longitude = models.FloatField()

    def __str__(self):
        return self.name

class Section(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class Author(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    bio = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.SET_NULL, null=True, blank=True, related_name='books')
    library = models.ForeignKey(Library, on_delete=models.SET_NULL, null=True, blank=True, related_name='books')
    section = models.ForeignKey(Section, on_delete=models.SET_NULL, null=True, blank=True, related_name='books')
    shelf = models.CharField(max_length=50, blank=True, null=True)
    row = models.CharField(max_length=50, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    published_date = models.DateField(null=True, blank=True)
    isbn = models.CharField(max_length=13, blank=True, null=True)
    cover_image = models.ImageField(upload_to='book_covers/', blank=True, null=True)
    ebook_file = models.FileField(upload_to='ebooks/', blank=True, null=True)

    def __str__(self):
        return self.title

class Reader(models.Model):
    fullname = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    card_id = models.CharField(max_length=50, unique=True)
    password_hash = models.CharField(max_length=255, default='')
    card_image = models.ImageField(upload_to='reader_cards/', blank=True, null=True)
    is_approved = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    session_token = models.CharField(max_length=128, blank=True, null=True)
    token_created_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.fullname

class Issue(models.Model):
    reader = models.ForeignKey(Reader, on_delete=models.CASCADE, related_name='issues')
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='issues')
    issue_date = models.DateField(auto_now_add=True)
    return_date = models.DateField()

    def __str__(self):
        return f"{self.reader.fullname} - {self.book.title}"


class Reservation(models.Model):
    reader = models.ForeignKey(Reader, on_delete=models.CASCADE, related_name='reservations')
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='reservations')
    reserved_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['reader', 'book'], name='unique_reader_book_reservation')
        ]

    def __str__(self):
        return f"{self.reader.fullname} reserved {self.book.title}"


class ReaderLibraryCard(models.Model):
    reader = models.ForeignKey(Reader, on_delete=models.CASCADE, related_name='library_cards')
    library = models.ForeignKey(Library, on_delete=models.CASCADE, related_name='reader_cards')
    card_image = models.ImageField(upload_to='reader_library_cards/')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['reader', 'library'], name='unique_reader_library_card')
        ]

    def __str__(self):
        return f"{self.reader.fullname} - {self.library.name}"
