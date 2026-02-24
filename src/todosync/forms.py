from django import forms

from .models import BaseTaskGroupTemplate


class BaseTaskGroupCreationForm(forms.Form):
    """Form for creating task groups from templates"""

    task_group_template = forms.ModelChoiceField(
        queryset=BaseTaskGroupTemplate.objects.all(),
        required=True,
        help_text="Select a task group template",
    )

    def __init__(self, *args, **kwargs):
        template_id = kwargs.pop("template_id", None)
        kwargs.pop("site", None)
        super().__init__(*args, **kwargs)

        token_field_names = []
        if template_id:
            try:
                template = BaseTaskGroupTemplate.objects.get(id=template_id)
                self.fields["task_group_template"].initial = template

                parent_task_model = template.get_parent_task_model()
                if parent_task_model:
                    token_field_names = parent_task_model.get_token_field_names()
                    for field_name in token_field_names:
                        try:
                            model_field = parent_task_model._meta.get_field(field_name)
                            placeholder = model_field.help_text or ""
                            self.fields[f"token_{field_name}"] = forms.CharField(
                                label=model_field.verbose_name.title() if model_field.verbose_name else field_name,
                                required=not model_field.blank,
                                max_length=getattr(model_field, "max_length", None),
                                widget=forms.TextInput(attrs={"placeholder": placeholder}),
                            )
                        except Exception:
                            self.fields[f"token_{field_name}"] = forms.CharField(
                                label=field_name.replace("_", " ").title(),
                                required=True,
                            )
            except BaseTaskGroupTemplate.DoesNotExist:
                pass

        if token_field_names:
            tokens = ", ".join(f"{{{name}}}" for name in token_field_names)
            desc_placeholder = f"Available tokens: {tokens}"
        else:
            desc_placeholder = "Optional additional description"
        self.fields["description"] = forms.CharField(
            label="Additional description",
            widget=forms.Textarea(attrs={"rows": 3, "placeholder": desc_placeholder}),
            required=False,
        )

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
