from app.db.generated import Prisma

prisma_client = Prisma()


async def connect_db() -> None:
    await prisma_client.connect()


async def disconnect_db() -> None:
    if prisma_client.is_connected():
        await prisma_client.disconnect()
