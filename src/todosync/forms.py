from django import forms
from .models import BaseTaskGroupTemplate


class BaseTaskGroupCreationForm(forms.Form):
    """Form for creating task groups from templates"""

    task_group_template = forms.ModelChoiceField(
        queryset=BaseTaskGroupTemplate.objects.all(),
        required=True,
        help_text="Select a task group template",
    )

    description = forms.CharField(
        label="Additional description",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        help_text="Optional additional description (with tokens).",
    )

    def __init__(self, *args, **kwargs):
        template_id = kwargs.pop("template_id", None)
        kwargs.pop("site", None)
        super().__init__(*args, **kwargs)

        if template_id:
            try:
                template = BaseTaskGroupTemplate.objects.get(id=template_id)
                self.fields["task_group_template"].initial = template

                parent_task_model = template.get_parent_task_model()
                if parent_task_model:
                    for field_name in parent_task_model.get_token_field_names():
                        try:
                            model_field = parent_task_model._meta.get_field(field_name)
                            self.fields[f"token_{field_name}"] = forms.CharField(
                                label=model_field.verbose_name.title()
                                if model_field.verbose_name
                                else field_name,
                                required=not model_field.blank,
                                help_text=model_field.help_text or "",
                                max_length=getattr(model_field, "max_length", None),
                            )
                        except Exception:
                            self.fields[f"token_{field_name}"] = forms.CharField(
                                label=field_name.replace("_", " ").title(),
                                required=True,
                            )
            except BaseTaskGroupTemplate.DoesNotExist:
                pass

    def get_token_values(self):
        """Extract token values from cleaned data"""
        if not hasattr(self, "cleaned_data"):
            return {}

        token_values = {}
        for key, value in self.cleaned_data.items():
            if key.startswith("token_"):
                token_name = key[len("token_") :]
                token_values[token_name] = value

        return token_values
