from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """Paginación por defecto con page_size sobrescribible por query string.

    Permite pedir ?page_size=1..100 para historiales acotados (por ejemplo,
    todos los viajes de un mes) sin perder la paginación por defecto.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
