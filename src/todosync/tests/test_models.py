import pytest
from django.core.exceptions import ValidationError

from todosync.models import TaskRule, TodoistSection


@pytest.fixture
def sow_tag(db):
    from taggit.models import Tag

    return Tag.objects.create(name="sow", slug="sow")


@pytest.fixture
def propagation_section(db):
    return TodoistSection.objects.create(
        key="propagation",
        section_id="sec123",
        name="Propagation",
    )


@pytest.mark.django_db
def test_task_rule_valid_condition_and_action(sow_tag, propagation_section):
    rule = TaskRule(
        rule_key="test_rule",
        trigger="completed_task",
        condition="label:sow",
        action="section:propagation",
    )
    rule.clean()  # should not raise


@pytest.mark.django_db
def test_task_rule_invalid_label_condition(db):
    rule = TaskRule(
        rule_key="test_rule",
        trigger="completed_task",
        condition="label:nonexistent",
        action="section:propagation",
    )
    with pytest.raises(ValidationError) as exc_info:
        rule.clean()
    assert "nonexistent" in str(exc_info.value)
    assert "condition" in exc_info.value.message_dict


@pytest.mark.django_db
def test_task_rule_invalid_section_action(db):
    rule = TaskRule(
        rule_key="test_rule",
        trigger="completed_task",
        condition="label:sow",
        action="section:nonexistent",
    )
    with pytest.raises(ValidationError) as exc_info:
        rule.clean()
    assert "nonexistent" in str(exc_info.value)
    assert "action" in exc_info.value.message_dict


@pytest.mark.django_db
def test_task_rule_both_invalid_reports_both_fields(db):
    rule = TaskRule(
        rule_key="test_rule",
        trigger="completed_task",
        condition="label:badlabel",
        action="section:badsection",
    )
    with pytest.raises(ValidationError) as exc_info:
        rule.clean()
    assert "condition" in exc_info.value.message_dict
    assert "action" in exc_info.value.message_dict


@pytest.mark.django_db
def test_task_rule_non_label_condition_not_validated(db):
    """Conditions that don't start with 'label:' skip tag lookup."""
    rule = TaskRule(
        rule_key="test_rule",
        trigger="completed_task",
        condition="some_other:value",
        action="irrelevant:value",
    )
    rule.clean()  # should not raise
