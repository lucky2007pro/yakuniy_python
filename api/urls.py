from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    LibraryViewSet,
    SectionViewSet,
    AuthorViewSet,
    BookViewSet,
    ReaderViewSet,
    IssueViewSet,
    ReservationViewSet,
    BookRatingViewSet,
    ReaderLibraryCardAdminViewSet,
)

router = DefaultRouter()
router.register(r'libraries', LibraryViewSet)
router.register(r'sections', SectionViewSet)
router.register(r'authors', AuthorViewSet)
router.register(r'books', BookViewSet)
router.register(r'readers', ReaderViewSet)
router.register(r'issues', IssueViewSet)
router.register(r'reservations', ReservationViewSet)
router.register(r'ratings', BookRatingViewSet)
router.register(r'library-cards-admin', ReaderLibraryCardAdminViewSet, basename='library-cards-admin')

urlpatterns = [
    path('', include(router.urls)),
]
