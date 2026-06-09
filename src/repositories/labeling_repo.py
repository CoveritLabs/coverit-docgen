# src/repositories/labeling_repo.py
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.orm import LabeledStateORM, LabeledElementORM
from src.models.graph import LabeledState, LabeledElement


class LabelingRepository:
    """Repository handling database operations for labeled artifacts."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_labeled_state(self, state: LabeledState) -> LabeledStateORM:
        """Saves a labeled state to the database."""
        db_state = LabeledStateORM(
            state_id=state.state_id, name=state.name, description=state.description
        )
        self.session.add(db_state)
        await self.session.commit()
        return db_state

    async def save_labeled_element(self, element: LabeledElement) -> LabeledElementORM:
        """Saves a labeled interactive element to the database."""
        db_element = LabeledElementORM(
            element_id=element.element_id,
            html_snippet=element.html_snippet,
            name=element.name,
            action=element.action,
        )
        self.session.add(db_element)
        await self.session.commit()
        return db_element
