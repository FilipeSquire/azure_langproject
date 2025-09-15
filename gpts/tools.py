

TOOLS = [{
    "type": "function",
    "function": {
        "name": "create_company_profile",
        "description": "Call when the user says something similar to: 'Create a company profile (CompanyName)'. Extract the name inside parentheses.",
        "parameters": {
            "type": "object",
            "properties": {"companyName": {"type": "string"}},
            "required": ["companyName"],
            "additionalProperties": False,
        },
    },
    "function": {
    "name": "add_company",
    "description": "Call when the user says something similar to: 'Add this company (CompanyNumber)'. Extract the number sequence inside parentheses.",
    "parameters": {
        "type": "object",
        "properties": {"companyNumber": {"type": "string"}},
        "required": ["companyNumber"],
        "additionalProperties": False,
        },
    },
    "function": {
    "name": "web_search",
    "description": "Call when the user mentions web_search in the phrase. Return True if it is mentioned otherwise False. ",
    "parameters": {
        "type": "object",
        "properties": {"webSearch": {"type": "string"}},
        "required": ["webSearch"],
        "additionalProperties": False,
        },
    },
}]

