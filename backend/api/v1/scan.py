from fastapi import APIRouter

router = APIRouter()


@router.post("/scan")
async def scan(payload: dict):

    return {
        "message": "Scan endpoint initialized",
        "payload": payload
    }