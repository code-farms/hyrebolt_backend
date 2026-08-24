from app.db.generated import Prisma


class BaseRepository:
    """Common constructor for repositories: they receive the connected Prisma
    client via dependency injection and never create their own connections."""

    def __init__(self, prisma: Prisma) -> None:
        self._prisma = prisma
