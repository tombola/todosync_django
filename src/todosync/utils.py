"""Utility functions for todosync package"""


def substitute_tokens(text, token_values):
    """
    Substitute tokens in text with their values.

    Args:
        text: Text containing tokens in {TOKEN} format
        token_values: Dict mapping token names to values

    Returns:
        Text with tokens replaced by their values

    Example:
        >>> substitute_tokens("Task for {SKU}", {"SKU": "CH001"})
        'Task for CH001'
    """
    result = text
    for token, value in token_values.items():
        result = result.replace(f"{{{token}}}", value)
    return result
