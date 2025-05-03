from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from mcp.server.fastmcp.prompts import base

def register_prompts(mcp):
    """Register all prompt templates with the MCP server."""
    
    @mcp.prompt()
    def create_transaction_prompt(amount: float, description: str, cashflow_type: str = "EXPENSE") -> str:
        """
        Create a prompt for adding a new transaction with essential information.
        
        Args:
            amount: The transaction amount (positive value)
            description: The transaction description
            cashflow_type: Type of transaction (INCOME or EXPENSE)
            
        Returns:
            A formatted prompt for creating a transaction
        """
        # Ensure cashflow_type is valid
        if cashflow_type not in ["INCOME", "EXPENSE"]:
            cashflow_type = "EXPENSE"  # Default to expense
        
        # Format amount sign based on cashflow type
        formatted_amount = amount if cashflow_type == "INCOME" else -amount
        
        return (
            f"Create a new {cashflow_type.lower()} transaction with the following details:\n\n"
            f"Amount: {formatted_amount} EUR\n"
            f"Description: {description}\n\n"
            f"Please confirm the transaction details before submitting. "
            f"You can also add more information such as VAT rate, transaction date, "
            f"or assign a specific category."
        )

    @mcp.prompt()
    def create_client_prompt(name: str, client_type: str = "business") -> str:
        """
        Create a prompt for adding a new client with basic information.
        
        Args:
            name: The client name or business name
            client_type: Type of client (business or private)
            
        Returns:
            A formatted prompt for creating a client
        """
        # Ensure client_type is valid
        if client_type not in ["business", "private"]:
            client_type = "business"  # Default to business
        
        return (
            f"Create a new {client_type} client with the following details:\n\n"
            f"Name: {name}\n\n"
            f"Please provide additional information about this client such as:\n"
            f"- Email address\n"
            f"- Phone number\n"
            f"- Physical address\n"
            f"- Country\n"
            f"- City and postal code\n"
            f"- VAT number (if applicable)"
        )

    @mcp.prompt()
    def send_invoice_prompt(invoice_id: str) -> List[base.Message]:
        """
        Create a prompt for sending an invoice via email.
        
        Args:
            invoice_id: ID of the invoice to send
            
        Returns:
            A list of messages forming a conversation about sending an invoice
        """
        return [
            base.UserMessage(f"I want to send invoice {invoice_id} to the client."),
            base.AssistantMessage("I'll help you send this invoice. What should the email subject line be?"),
            base.UserMessage("Invoice for your recent order"),
            base.AssistantMessage("Great! And what message would you like to include in the email body?"),
            base.UserMessage("Dear Client,\n\nPlease find attached the invoice for your recent order. Payment is due within 14 days.\n\nThank you for your business!\n\nBest regards,"),
            base.AssistantMessage("Would you like to send a copy to yourself or any additional recipients?"),
            base.UserMessage("Yes, please send a copy to myself."),
            base.AssistantMessage("I'll prepare the email with the invoice attachment and send it to the client with a copy to you. Would you like to review the email before sending?")
        ]

    @mcp.prompt()
    def search_transactions_prompt(date_range: Optional[str] = None) -> str:
        """
        Create a prompt for searching transactions with optional date range.
        
        Args:
            date_range: Optional description of date range (e.g., "last month", "this week")
            
        Returns:
            A formatted prompt for searching transactions
        """
        base_text = "I want to search for transactions"
        
        if date_range:
            base_text += f" from {date_range}"
        
        return (
            f"{base_text}.\n\n"
            f"Please help me find transactions by specifying any of these search criteria:\n"
            f"- Description text to search for\n"
            f"- Specific date range (YYYY-MM-DD format)\n"
            f"- Amount range (minimum and maximum values)\n"
            f"- Transaction category\n"
            f"- Transaction status (VERIFIED, UNVERIFIED)\n"
            f"- Cashflow type (INCOME, EXPENSE)\n"
            f"- Only transactions without invoices or receipts\n\n"
            f"You can combine multiple criteria to narrow down the search results."
        )

    @mcp.prompt()
    def tax_report_prompt(report_id: str) -> List[base.Message]:
        """
        Create a prompt for handling a tax report.
        
        Args:
            report_id: ID of the tax report
            
        Returns:
            A list of messages forming a conversation about tax report handling
        """
        return [
            base.UserMessage(f"I want to prepare and submit tax report {report_id}."),
            base.AssistantMessage("I'll help you with the tax report. First, let me get the report details and generate a preview for your review."),
            base.UserMessage("Please show me the report details and totals."),
            base.AssistantMessage("I'll fetch the report data and show you the key information. Would you like me to generate a PDF preview that you can check before submission?"),
            base.UserMessage("Yes, please generate a preview."),
            base.AssistantMessage("I'll generate a preview PDF. Once you've reviewed it, let me know if you want to:\n1. Make any adjustments\n2. Submit the report to Finanzamt\n3. Save it for later")
        ]

    @mcp.prompt()
    def upload_documents_prompt(file_paths: List[str], cashflow_type: Optional[str] = None) -> str:
        """
        Create a prompt for uploading multiple documents.
        
        Args:
            file_paths: List of paths to files to upload
            cashflow_type: Optional cashflow type (INCOME or EXPENSE)
            
        Returns:
            A formatted prompt for uploading documents
        """
        files_count = len(file_paths)
        file_list = "\n".join(f"- {path}" for path in file_paths)
        
        return (
            f"I'll help you upload {files_count} document{'s' if files_count > 1 else ''}:\n"
            f"{file_list}\n\n"
            f"For each document, you can specify:\n"
            f"- Document type (invoice, receipt, contract, other)\n"
            f"- Transaction to link it to\n"
            f"- Amount and currency\n"
            f"- Description\n"
            f"- Date\n"
            f"- VAT information\n\n"
            f"{'The documents will be marked as ' + cashflow_type.lower() + '.' if cashflow_type else ''}"
        )

    @mcp.prompt()
    def overdue_reminder_prompt(invoice_id: str, days_overdue: int) -> str:
        """
        Create a prompt for sending an overdue payment reminder.
        
        Args:
            invoice_id: ID of the overdue invoice
            days_overdue: Number of days the invoice is overdue
            
        Returns:
            A formatted prompt for sending a payment reminder
        """
        return (
            f"I'll help you send a payment reminder for invoice {invoice_id}, "
            f"which is {days_overdue} days overdue.\n\n"
            f"Would you like to:\n"
            f"1. Send a friendly first reminder\n"
            f"2. Send a firm second reminder\n"
            f"3. Send a final notice\n\n"
            f"I can help you customize:\n"
            f"- Email subject and message\n"
            f"- Additional recipients\n"
            f"- Whether to include the original invoice\n"
            f"- Whether to send a copy to yourself"
        ) 