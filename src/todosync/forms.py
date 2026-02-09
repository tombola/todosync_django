from django import forms
from .models import BaseTaskGroupTemplate, TaskSyncSettings


class BaseTaskGroupCreationForm(forms.Form):
    """Form for creating task groups from templates"""

    task_group_template = forms.ModelChoiceField(
        queryset=BaseTaskGroupTemplate.objects.live(),
        required=True,
        help_text="Select a task group template"
    )

    description = forms.CharField(
        label="Additional description",
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
        help_text="Optional additional description (with tokens)."
    )

    def __init__(self, *args, **kwargs):
        template_id = kwargs.pop('template_id', None)
        site = kwargs.pop('site', None)
        super().__init__(*args, **kwargs)

        # If a template is selected, add dynamic token fields and set initial value
        if template_id:
            try:
                template = BaseTaskGroupTemplate.objects.get(id=template_id)

                # Set initial value for task_group_template field
                self.fields['task_group_template'].initial = template

                # Get tokens from site settings
                if site:
                    sync_settings = TaskSyncSettings.for_site(site)
                    tokens = sync_settings.get_token_list()
                else:
                    tokens = []

                for token in tokens:
                    field_name = f'token_{token}'
                    self.fields[field_name] = forms.CharField(
                        label=token,
                        required=True,
                    )
            except BaseTaskGroupTemplate.DoesNotExist:
                pass

    def get_token_values(self):
        """Extract token values from cleaned data"""
        if not hasattr(self, 'cleaned_data'):
            return {}

        token_values = {}
        for key, value in self.cleaned_data.items():
            if key.startswith('token_'):
                token_name = key.replace('token_', '')
                token_values[token_name] = value

        return token_values
