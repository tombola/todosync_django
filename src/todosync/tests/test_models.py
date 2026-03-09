import pytest

from todosync.models import TodoistSection


@pytest.fixture
def propagation_section(db):
    return TodoistSection.objects.create(
        key="propagation",
        section_id="sec123",
        name="Propagation",
    )


@pytest.mark.django_db
def test_todoistsection_str(propagation_section):
    assert str(propagation_section) == "propagation (sec123)"


@pytest.mark.django_db
def test_todoistsection_key_unique(db):
    TodoistSection.objects.create(key="beds", section_id="sec456", name="Beds")
    with pytest.raises(Exception):
        TodoistSection.objects.create(key="beds", section_id="sec789", name="Beds 2")
