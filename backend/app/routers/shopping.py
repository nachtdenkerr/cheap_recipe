"""Shopping list endpoints: what the latest plan buys, and what is ticked off."""

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import update

from app.deps import CurrentUser, SessionDep
from app.presenters import latest_generation, shopping_list
from app.schemas.shopping import CheckUpdate, ShoppingListItem
from cheaprecipe.db.models import GenerationItem

router = APIRouter(prefix="/shopping", tags=["shopping"])


@router.get("")
def get_shopping_list(user: CurrentUser, session: SessionDep) -> list[ShoppingListItem]:
    generation = latest_generation(session, user)
    return shopping_list(generation) if generation else []


@router.patch("/{item_id}")
def set_checked(
    item_id: int, body: CheckUpdate, user: CurrentUser, session: SessionDep
) -> ShoppingListItem:
    item = session.get(GenerationItem, item_id)
    # Offer or regular-price line alike, it must be on the list: a row the
    # meal plan does not use (or a pantry staple) cannot be ticked.
    on_list = (
        item is not None
        and item.generation.user_id == user.id
        and any(line.id == item_id for line in shopping_list(item.generation))
    )
    if not on_list:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shopping list item not found")
    item.checked = body.checked
    session.commit()
    return next(line for line in shopping_list(item.generation) if line.id == item_id)


@router.post("/uncheck-all", status_code=status.HTTP_204_NO_CONTENT)
def uncheck_all(user: CurrentUser, session: SessionDep) -> Response:
    generation = latest_generation(session, user)
    if generation is not None:
        session.execute(
            update(GenerationItem)
            .where(GenerationItem.generation_id == generation.id)
            .values(checked=False)
        )
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
