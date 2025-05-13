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
        choice_type: str = Field(description="Type of choices to retrieve (options: 'civil-status', 'genders', 'religions', 'income-taxation-methods', 'profession-founding-articles', 'tax-states', 'profit-detections')")
    ) -> Dict[str, Any]:
        """
        Get choices/options for tax registration fields.
        
        Args:
            choice_type: Type of choices to retrieve (options: 'civil-status', 'genders', 'religions', 'income-taxation-methods', 'profession-founding-articles', 'tax-states', 'profit-detections')
            
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
        # Step 1 fields
        civil_status: str = Field(default='001', description="Civil status code. Use get_tax_registration_choices 'civil-status' to get the list of available choices."),
        civil_status_changed_since: Optional[str] = Field(default=None, description="Date when civil status changed (YYYY-MM-DD). Only if civil_status not '001'"),
        person_a_gender: int = Field(default=None, description="Filer person gender code. Use get_tax_registration_choices 'genders' to get the list of available choices."),
        person_a_last_name: str = Field(default=None, description="Filer person last name"),
        person_a_first_name: str = Field(default=None, description="Filer person first name"),
        person_a_birth_name: Optional[str] = Field(default=None, description="Filer person birth name"),
        person_a_current_profession: Optional[str] = Field(default=None, description="Filer person current profession"),
        person_a_dob: str = Field(default=None, description="Filer person date of birth (YYYY-MM-DD)"),
        person_a_street: str = Field(default=None, description="Filer person residence street name"),
        person_a_house_number: str = Field(default=None, description="Filer person residence house number"),
        person_a_apartment_number: Optional[str] = Field(default=None, description="Filer person residence apartment number"),
        person_a_address_ext: Optional[str] = Field(default=None, description="Filer person residence address additional info"),
        person_a_city: str = Field(default=None, description="Filer person residence city name"),
        person_a_post_code: str = Field(default=None, description="Filer person residence post code"),
        uses_post_office_box: Optional[bool] = Field(default=False, description="Whether filer person uses post office box"),
        person_a_religion: str = Field(default="11", description="Filer person religion code. Use get_tax_registration_choices 'religions' to get the list of available choices."),
        person_a_email: Optional[str] = Field(default=None, description="Filer person email"),
        person_a_phone_number: Optional[str] = Field(default=None, description="Filer person phone number"),
        person_a_website: Optional[str] = Field(default=None, description="Filer person website"),
        person_a_idnr: str = Field(default=None, description="Filer person tax ID number. German format. Example: 79 538 461 449"),
        # Basic spouse fields (can be expanded as needed)
        person_b_same_address: bool = Field(default=True, description="Whether spouse has same address"),
        moved_from_other_german_city: bool = Field(default=False, description="Whether person moved from other German city. You should ask the user"),
        person_b_gender: int = Field(default=None, description="Spouse gender code. Use get_tax_registration_choices 'genders' to get the list of available choices. Only if civil_status not '001'"),
        person_b_last_name: str = Field(default=None, description="Spouse last name. Only if civil_status not '001'"),
        person_b_first_name: str = Field(default=None, description="Spouse first name. Only if civil_status not '001'"),
        person_b_birth_name: Optional[str] = Field(default=None, description="Spouse birth name. Only if civil_status not '001'"),
        person_b_current_profession: Optional[str] = Field(default=None, description="Spouse current profession in German. Only if civil_status not '001'"),
        person_b_dob: str = Field(default=None, description="Spouse date of birth (YYYY-MM-DD). Only if civil_status not '001'"),
        person_b_street: str = Field(default=None, description="Spouse residence street name. Only if civil_status not '001' and person_b_same_address is False"),
        person_b_house_number: str = Field(default=None, description="Spouse residence house number. Only if civil_status not '001' and person_b_same_address is False"),
        person_b_apartment_number: Optional[str] = Field(default=None, description="Spouse residence apartment number. Only if civil_status not '001' and person_b_same_address is False"),
        person_b_address_ext: Optional[str] = Field(default=None, description="Spouse residence address additional info. Only if civil_status not '001' and person_b_same_address is False"),
        person_b_city: str = Field(default=None, description="Spouse residence city name. Only if civil_status not '001' and person_b_same_address is False"),
        person_b_post_code: str = Field(default=None, description="Spouse residence post code. Only if civil_status not '001' and person_b_same_address is False"),
        person_b_idnr: Optional[str] = Field(default=None, description="Spouse tax ID number. German format. Example: 79 538 461 449. Only if civil_status not '001'. Trim whitespaces."),
        person_b_religion: str = Field(default="11", description="Spouse religion code. Use get_tax_registration_choices 'religions' to get the list of available choices. Only if civil_status not '001'"),
        person_a_other_city_moving_date: str = Field(default=None, description="Date when person moved from other German city (YYYY-MM-DD). Only if moved_from_other_german_city is True"),
        person_a_other_city_moving_street: Optional[str] = Field(default=None, description="Person moved from other German city street name. Only if moved_from_other_german_city is True"),
        person_a_other_city_moving_house_number: Optional[str] = Field(default=None, description="Person moved from other German city house number. Only if moved_from_other_german_city is True"),
        person_a_other_city_moving_apartment_number: Optional[str] = Field(default=None, description="Person moved from other German city apartment number. Only if moved_from_other_german_city is True"),
        person_a_other_city_moving_address_ext: Optional[str] = Field(default=None, description="Person moved from other German city address additional info. Only if moved_from_other_german_city is True"),
        person_a_other_city_moving_city: str = Field(default=None, description="Person moved from other German city city name. Only if moved_from_other_german_city is True"),
        person_a_other_city_moving_post_code: str = Field(default=None, description="Person moved from other German city post code. Only if moved_from_other_german_city is True")
    ) -> Dict[str, Any]:
        """
        This tool is used to file a new self-employed tax registration with the Finanzamt (Fragebogen zur steuerlichen Erfassung).
        Create a new tax registration. You should call this tool first and then call update_tax_registration for each step.
        Ask the user for the information needed for each step. 
        You can get the list of available choices for each field using get_tax_registration_choices.
        You can get the public_id from the response of this tool.
        You can update the tax registration using update_tax_registration.
        
        Args:
            step: Registration step (1-6)
            source: Registration source
            external_user_id: External user ID (UUID)
            ... various fields depending on the step
            
        Returns:
            Created tax registration data
        """
        api = ctx.request_context.lifespan_context.get("api")
        registration_url = urljoin(config.api_base_url, "api/v1/tax-registration/")
        
        # Generate UUID if not provided
        external_user_id = str(uuid.uuid4())
        source = "norman_external"
        
        # Create base payload
        payload = {
            "step": 1,
            "source": source,
            "externalUserId": external_user_id,
            "personAGender": person_a_gender,
            "personALastName": person_a_last_name,
            "personAFirstName": person_a_first_name,
            "personABirthName": person_a_birth_name,
            "personACurrentProfession": person_a_current_profession,
            "personADob": person_a_dob,
            "personAStreet": person_a_street,
            "personAHouseNumber": person_a_house_number,
            "personAApartmentNumber": person_a_apartment_number,
            "personAAddressExt": person_a_address_ext,
            "personACity": person_a_city,
            "personAPostCode": person_a_post_code,
            "personAReligion": person_a_religion,
            "personAEmail": person_a_email,
            "personAPhoneNumber": person_a_phone_number,
            "personAWebsite": person_a_website,
            "personAIdnr": person_a_idnr,
            "civilStatus": civil_status,
            "movedFromOtherGermanCity": moved_from_other_german_city
        }

        if uses_post_office_box:
            payload["usesPostOfficeBox"] = uses_post_office_box
            # payload["personAPostOfficeBox"] = person_a_post_office_box
            # payload["personAPostOfficeBoxPostCode"] = person_a_post_office_box_post_code
            # payload["personAPostOfficeBoxCity"] = person_a_post_office_box_city
        
        if civil_status != "001":
            payload["civilStatusChangedSince"] = civil_status_changed_since
            payload["personBGender"] = person_b_gender
            payload["personBLastName"] = person_b_last_name
            payload["personBFirstName"] = person_b_first_name
            payload["personBBirthName"] = person_b_birth_name
            payload["personBCurrentProfession"] = person_b_current_profession
            payload["personBDob"] = person_b_dob
            payload["personBSameAddress"] = person_b_same_address
            payload["personBIdnr"] = person_b_idnr
            payload["personBReligion"] = person_b_religion
            if person_b_same_address:
                payload["personBStreet"] = person_b_street
                payload["personBHouseNumber"] = person_b_house_number
                payload["personBApartmentNumber"] = person_b_apartment_number
                payload["personBAddressExt"] = person_b_address_ext
                payload["personBCity"] = person_b_city
                payload["personBPostCode"] = person_b_post_code
        
        if moved_from_other_german_city:
            payload["personAOtherCityMovingDate"] = person_a_other_city_moving_date
            payload["personAOtherCityMovingStreet"] = person_a_other_city_moving_street
            payload["personAOtherCityMovingHouseNumber"] = person_a_other_city_moving_house_number
            payload["personAOtherCityMovingApartmentNumber"] = person_a_other_city_moving_apartment_number
            payload["personAOtherCityMovingAddressExt"] = person_a_other_city_moving_address_ext
            payload["personAOtherCityMovingCity"] = person_a_other_city_moving_city
            payload["personAOtherCityMovingPostCode"] = person_a_other_city_moving_post_code
        
        
        return api._make_request("POST", registration_url, json_data=payload, skip_auth=True)
    
    @mcp.tool()
    async def update_tax_registration(
        ctx: Context,
        public_id: str = Field(description="Public ID of the tax registration to update.  Get it from create_tax_registration"),
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

        registration_url = urljoin(config.api_base_url, f"api/v1/tax-registration/{public_id}/")
        
        # Create payload with all provided fields
        payload = {}
        for key, value in ctx.parameters.items():
            if key != "public_id" and value is not None:
                payload[key] = value
        
        return api._make_request("PATCH", registration_url, json_data=payload, skip_auth=True)
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

        if public_id:
            registration_url = urljoin(config.api_base_url, f"api/v1/tax-registration/{public_id}/")
            params = {}
        else:
            registration_url = urljoin(config.api_base_url, "api/v1/tax-registration/my/")
            params = {"external_user_id": external_user_id}
        
        return api._make_request("GET", registration_url, params=params, skip_auth=True)
    
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
        submit_url = urljoin(config.api_base_url, f"api/v1/tax-registration/{public_id}/submit/")

        return api._make_request("POST", submit_url)
    
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

        
        check_url = urljoin(config.api_base_url, "api/v1/tax-registration/check-is-submitted/")
        params = {"external_user_id": external_user_id}
        
        return api._make_request("GET", check_url, params=params, skip_auth=True)
