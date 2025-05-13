import logging
import requests
import io
import uuid
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
from pydantic import Field
from mcp.server.fastmcp.utilities.types import Image
from pdf2image import convert_from_bytes
from PIL import Image as PILImage

from norman_mcp.context import Context
from norman_mcp import config

logger = logging.getLogger(__name__)

def register_tax_registration_tools(mcp):
    """Register all tax registration related tools with the MCP server."""
    
    @mcp.tool()
    async def get_tax_registration_choices(
        ctx: Context,
        choice_type: str = Field(description="Type of choices to retrieve (e.g., 'civil-status', 'genders', 'religions', etc.)")
    ) -> Dict[str, Any]:
        """
        Get choices/options for tax registration fields.
        
        Args:
            choice_type: Type of choices to retrieve (e.g., 'civil_status', 'gender', 'religion', etc.)
            
        Returns:
            Dictionary of choices with their values and labels
        """
        api = ctx.request_context.lifespan_context.get("api")
        
        choices_url = urljoin(config.api_base_url, f"api/v1/choices/{choice_type}/")
        
        response = api._make_request("GET", choices_url, skip_auth=True)
        if isinstance(response, list):
            return {"choices": response}
        return response
    
    @mcp.tool()
    async def create_tax_registration(
        ctx: Context,
        step: int = Field(default=1, description="Registration step (1-6)"),
        source: str = Field(default="NORMAN_EXTERNAL", description="Registration source"),
        external_user_id: Optional[str] = Field(default=None, description="External user ID (UUID)"),
        # Step 1 fields
        civil_status: Optional[str] = Field(default=None, description="Civil status code"),
        civil_status_changed_since: Optional[str] = Field(default=None, description="Date when civil status changed (YYYY-MM-DD)"),
        person_a_gender: Optional[str] = Field(default=None, description="Person A gender code"),
        person_a_last_name: Optional[str] = Field(default=None, description="Person A last name"),
        person_a_first_name: Optional[str] = Field(default=None, description="Person A first name"),
        person_a_birth_name: Optional[str] = Field(default=None, description="Person A birth name"),
        person_a_current_profession: Optional[str] = Field(default=None, description="Person A current profession"),
        person_a_dob: Optional[str] = Field(default=None, description="Person A date of birth (YYYY-MM-DD)"),
        person_a_street: Optional[str] = Field(default=None, description="Person A street name"),
        person_a_house_number: Optional[str] = Field(default=None, description="Person A house number"),
        person_a_apartment_number: Optional[str] = Field(default=None, description="Person A apartment number"),
        person_a_address_ext: Optional[str] = Field(default=None, description="Person A address additional info"),
        person_a_city: Optional[str] = Field(default=None, description="Person A city name"),
        person_a_post_code: Optional[str] = Field(default=None, description="Person A post code"),
        uses_post_office_box: Optional[bool] = Field(default=None, description="Whether person A uses post office box"),
        person_a_religion: Optional[str] = Field(default=None, description="Person A religion code"),
        person_a_idnr: Optional[str] = Field(default=None, description="Person A tax ID"),
        person_a_email: Optional[str] = Field(default=None, description="Person A email"),
        person_a_phone_number: Optional[str] = Field(default=None, description="Person A phone number"),
        # Basic spouse fields (can be expanded as needed)
        person_b_same_address: Optional[bool] = Field(default=None, description="Whether person B has same address"),
        moved_from_other_german_city: Optional[bool] = Field(default=None, description="Whether person moved from other German city")
    ) -> Dict[str, Any]:
        """
        Create a new tax registration.
        
        Args:
            step: Registration step (1-6)
            source: Registration source
            external_user_id: External user ID (UUID)
            ... various fields depending on the step
            
        Returns:
            Created tax registration data
        """
        api = ctx.request_context.lifespan_context.get("api")
        if not api:
            # Handle case when running without auth
            headers = {}
        else:
            headers = {"Authorization": f"Bearer {api.access_token}"}
        
        registration_url = urljoin(config.api_base_url, "api/v1/tax-registration/")
        
        # Generate UUID if not provided
        if not external_user_id:
            external_user_id = str(uuid.uuid4())
        
        # Create base payload
        payload = {
            "step": step,
            "source": source,
            "external_user_id": external_user_id
        }
        
        # Add all other provided fields
        for key, value in ctx.parameters.items():
            if key not in ["step", "source", "external_user_id"] and value is not None:
                payload[key] = value
        
        try:
            response = requests.post(
                registration_url,
                json=payload,
                headers=headers,
                timeout=config.NORMAN_API_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create tax registration: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise ValueError(f"Failed to create tax registration: {str(e)}")
    
    @mcp.tool()
    async def update_tax_registration(
        ctx: Context,
        public_id: str = Field(description="Public ID of the tax registration to update"),
        step: Optional[int] = Field(default=None, description="Registration step (1-6)"),
        # Step 2 fields
        profession_description: Optional[str] = Field(default=None, description="Profession description"),
        profession_founding_article: Optional[str] = Field(default=None, description="Profession founding article"),
        business_started_activity_date: Optional[str] = Field(default=None, description="Business started activity date (YYYY-MM-DD)"),
        business_has_separated_office: Optional[bool] = Field(default=None, description="Whether business has separated office"),
        has_previous_business_in_germany: Optional[bool] = Field(default=None, description="Whether has previous business in Germany"),
        # Step 3 fields
        have_already_tax_number: Optional[bool] = Field(default=None, description="Whether already has tax number"),
        previous_tax_number: Optional[str] = Field(default=None, description="Previous tax number"),
        previous_tax_number_state: Optional[str] = Field(default=None, description="Previous tax number state"),
        profit_determination_method: Optional[str] = Field(default=None, description="Profit determination method"),
        profession_founding_date: Optional[str] = Field(default=None, description="Profession founding date (YYYY-MM-DD)"),
        estimated_revenue_for_current_year: Optional[int] = Field(default=None, description="Estimated revenue for current year"),
        estimated_revenue_for_next_year: Optional[int] = Field(default=None, description="Estimated revenue for next year"),
        kleinunternehmer_charge_vat: Optional[bool] = Field(default=None, description="Whether kleinunternehmer charge VAT"),
        need_vat_number: Optional[bool] = Field(default=None, description="Whether need VAT number"),
        income_taxation_method: Optional[str] = Field(default=None, description="Income taxation method"),
        # Step 4 - expected profit fields can be added as needed
        estimated_vat_pay_current_year: Optional[float] = Field(default=None, description="Estimated VAT to pay in current year"),
        # Step 5 fields
        has_separate_business_bank_account: Optional[bool] = Field(default=None, description="Whether has separate business bank account"),
        business_bank_account_iban: Optional[str] = Field(default=None, description="Business bank account IBAN"),
        business_bank_account_owner: Optional[str] = Field(default=None, description="Business bank account owner"),
        private_bank_account_iban: Optional[str] = Field(default=None, description="Private bank account IBAN"),
        private_bank_account_owner: Optional[str] = Field(default=None, description="Private bank account owner"),
        # Step 6 fields
        tax_office: Optional[str] = Field(default=None, description="Tax office code")
    ) -> Dict[str, Any]:
        """
        Update a tax registration.
        
        Args:
            public_id: Public ID of the tax registration to update
            step: Registration step (1-6)
            ... various fields depending on the step
            
        Returns:
            Updated tax registration data
        """
        api = ctx.request_context.lifespan_context.get("api")
        if not api:
            # Handle case when running without auth
            headers = {}
        else:
            headers = {"Authorization": f"Bearer {api.access_token}"}
        
        registration_url = urljoin(config.api_base_url, f"api/v1/tax-registration/{public_id}/")
        
        # Create payload with all provided fields
        payload = {}
        for key, value in ctx.parameters.items():
            if key != "public_id" and value is not None:
                payload[key] = value
        
        try:
            response = requests.patch(
                registration_url,
                json=payload,
                headers=headers,
                timeout=config.NORMAN_API_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to update tax registration: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise ValueError(f"Failed to update tax registration: {str(e)}")
    
    @mcp.tool()
    async def get_tax_registration(
        ctx: Context,
        external_user_id: Optional[str] = Field(default=None, description="External user ID"),
        public_id: Optional[str] = Field(default=None, description="Public ID of the tax registration")
    ) -> Dict[str, Any]:
        """
        Get a tax registration.
        
        Args:
            external_user_id: External user ID
            public_id: Public ID of the tax registration
            
        Returns:
            Tax registration data
        """
        api = ctx.request_context.lifespan_context.get("api")
        if not api:
            # Handle case when running without auth
            headers = {}
        else:
            headers = {"Authorization": f"Bearer {api.access_token}"}
        
        if public_id:
            registration_url = urljoin(config.api_base_url, f"api/v1/tax-registration/{public_id}/")
            params = {}
        else:
            registration_url = urljoin(config.api_base_url, "api/v1/tax-registration/my/")
            params = {"external_user_id": external_user_id}
        
        try:
            response = requests.get(
                registration_url,
                params=params,
                headers=headers,
                timeout=config.NORMAN_API_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get tax registration: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise ValueError(f"Failed to get tax registration: {str(e)}")
    
    @mcp.tool()
    async def generate_registration_preview(
        ctx: Context,
        public_id: str = Field(description="Public ID of the tax registration to generate preview for")
    ) -> Image:
        """
        Generate a preview of the tax registration and return it as an image.
        
        Args:
            public_id: Public ID of the tax registration
            
        Returns:
            Tax registration preview as an image
        """
        api = ctx.request_context.lifespan_context.get("api")
        if not api:
            # Handle case when running without auth
            headers = {}
        else:
            headers = {"Authorization": f"Bearer {api.access_token}"}
        
        preview_url = urljoin(config.api_base_url, f"api/v1/tax-registration/{public_id}/preview/")
        
        try:
            response = requests.post(
                preview_url,
                headers=headers,
                timeout=config.NORMAN_API_TIMEOUT
            )
            response.raise_for_status()
            
            # Convert PDF bytes to image
            if isinstance(response.content, bytes) and len(response.content) > 0:
                # Convert PDF to image
                images = convert_from_bytes(response.content, dpi=150)
                
                # Get the first page as PIL Image
                first_page = images[0]
                
                # Convert to RGB and resize if needed to keep file size manageable
                first_page = first_page.convert('RGB')
                
                # Calculate new dimensions while maintaining aspect ratio
                width, height = first_page.size
                max_dim = 1000
                if width > max_dim or height > max_dim:
                    if width > height:
                        new_width = max_dim
                        new_height = int(height * (max_dim / width))
                    else:
                        new_height = max_dim
                        new_width = int(width * (max_dim / height))
                    first_page = first_page.resize((new_width, new_height), PILImage.LANCZOS)
                
                # Save as PNG to bytes buffer
                buffer = io.BytesIO()
                first_page.save(buffer, format="PNG", optimize=True)
                buffer.seek(0)
                
                # Return as Image
                return Image(data=buffer.getvalue(), format="png")
            else:
                raise ValueError("Preview generation failed or invalid response format")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to generate registration preview: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise ValueError(f"Failed to generate registration preview: {str(e)}")
        except Exception as e:
            logger.error(f"Error generating registration preview: {str(e)}")
            raise ValueError(f"Error generating registration preview: {str(e)}")
    
    @mcp.tool()
    async def submit_tax_registration(
        ctx: Context,
        public_id: str = Field(description="Public ID of the tax registration to submit")
    ) -> Dict[str, Any]:
        """
        Submit a tax registration to the Finanzamt.
        
        Args:
            public_id: Public ID of the tax registration
            
        Returns:
            Response from the submission
        """
        api = ctx.request_context.lifespan_context.get("api")
        if not api:
            # Handle case when running without auth
            headers = {}
        else:
            headers = {"Authorization": f"Bearer {api.access_token}"}
        
        submit_url = urljoin(config.api_base_url, f"api/v1/tax-registration/{public_id}/submit/")
        
        try:
            response = requests.post(
                submit_url,
                headers=headers,
                timeout=config.NORMAN_API_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to submit tax registration: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise ValueError(f"Failed to submit tax registration: {str(e)}")
    
    @mcp.tool()
    async def check_tax_registration_submitted(
        ctx: Context,
        external_user_id: str = Field(description="External user ID of the tax registration")
    ) -> Dict[str, Any]:
        """
        Check if a tax registration has been submitted.
        
        Args:
            external_user_id: External user ID of the tax registration
            
        Returns:
            Submission status information
        """
        api = ctx.request_context.lifespan_context.get("api")
        if not api:
            # Handle case when running without auth
            headers = {}
        else:
            headers = {"Authorization": f"Bearer {api.access_token}"}
        
        check_url = urljoin(config.api_base_url, "api/v1/tax-registration/check-is-submitted/")
        params = {"external_user_id": external_user_id}
        
        try:
            response = requests.get(
                check_url,
                params=params,
                headers=headers,
                timeout=config.NORMAN_API_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to check tax registration submission: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise ValueError(f"Failed to check tax registration submission: {str(e)}") 