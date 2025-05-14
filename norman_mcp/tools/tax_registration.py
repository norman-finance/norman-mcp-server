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
from norman_mcp.resources.tax_offices import get_all_tax_offices

logger = logging.getLogger(__name__)

NORMAN_AGENT_SOURCE = "norman_agent"

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
    async def get_tax_offices(
        ctx: Context,
        search_term: Optional[str] = Field(default=None, description="Optional search term to filter tax offices by name")
    ) -> Dict[str, Any]:
        """
        Get a list of tax offices in Germany.
        
        Args:
            search_term: Optional search term to filter tax offices by name
            
        Returns:
            Dictionary with a list of tax offices
        """
        tax_offices = get_all_tax_offices()
        
        if search_term and search_term.strip():
            search_term = search_term.lower()
            filtered_offices = [
                office for office in tax_offices 
                if search_term in office["label"].lower()
            ]
            return {"tax_offices": filtered_offices}
        
        return {"tax_offices": tax_offices}
    
    @mcp.tool()
    async def create_tax_registration(
        ctx: Context,
        # Step 1 fields
        locale: str = Field(default="en", description="Locale of the tax registration. Use 'de' for German and 'en' for English. Detect it automatically."),
        civil_status: str = Field(default='001', description="Civil status code. Use get_tax_registration_choices 'civil-status' to get the list of available choices."),
        civil_status_changed_since: Optional[str] = Field(default=None, description="Date when civil status changed (YYYY-MM-DD). Only if civil_status not '001'"),
        person_a_gender: int = Field(default=None, description="Filer person gender code. Use get_tax_registration_choices 'genders' to get the list of available choices. Always ask the user for the gender."),
        person_a_last_name: str = Field(default=None, description="Filer person last name"),
        person_a_first_name: str = Field(default=None, description="Filer person first name"),
        person_a_birth_name: str = Field(default="", description="Filer person birth name"),
        person_a_current_profession: str = Field(default="", description="Filer person current profession"),
        person_a_dob: str = Field(default=None, description="Filer person date of birth (YYYY-MM-DD)"),
        person_a_street: str = Field(default=None, description="Filer person residence street name"),
        person_a_house_number: str = Field(default=None, description="Filer person residence house number"),
        person_a_apartment_number: str = Field(default=None, description="Filer person residence apartment number"),
        person_a_address_ext: str = Field(default="", description="Filer person residence address additional info"),
        person_a_city: str = Field(default=None, description="Filer person residence city name"),
        person_a_post_code: str = Field(default=None, description="Filer person residence post code"),
        uses_post_office_box: Optional[bool] = Field(default=False, description="Whether filer person uses post office box"),
        person_a_religion: str = Field(default="11", description="Filer person religion code. Use get_tax_registration_choices 'religions' to get the list of available choices. Always ask the user for the religion."),
        person_a_email: Optional[str] = Field(default=None, description="Filer person email"),
        person_a_phone_number: Optional[str] = Field(default=None, description="Filer person phone number"),
        person_a_website: str = Field(default="", description="Filer person website"),
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
        Ask the user for the information needed for each step. Make it as simple as possible and asking step by step.
        You can get the list of available choices for each field using get_tax_registration_choices.
        You can get the public_id from the response of this tool.
        You can update the tax registration using update_tax_registration.
        Also use session_key from the response of this tool to update the tax registration.
        
        Args:
            civil_status: (Required) Civil status code. Use get_tax_registration_choices 'civil-status' to get the list of available choices.
            civil_status_changed_since: (Optional) Date when civil status changed (YYYY-MM-DD). Only if civil_status not '001'.
            person_a_gender: (Required) Filer person gender code. Use get_tax_registration_choices 'genders' to get the list of available choices. Always ask the user for the gender.
            person_a_last_name: (Required) Filer person last name.
            person_a_first_name: (Required) Filer person first name.
            person_a_birth_name: (Required) Filer person birth name. By default it's an empty string.
            person_a_current_profession: (Optional) Filer person current profession.
            person_a_dob: (Required) Filer person date of birth (YYYY-MM-DD).
            person_a_street: (Required) Filer person residence street name.
            person_a_house_number: (Required) Filer person residence house number.
            person_a_apartment_number: (Required) Filer person residence apartment number.
            person_a_address_ext: (Optional) Filer person residence address additional info.
            person_a_city: (Required) Filer person residence city name.
            person_a_post_code: (Required) Filer person residence post code.
            uses_post_office_box: (Optional) Whether filer person uses post office box.
            person_a_religion: (Required) Filer person religion code. Use get_tax_registration_choices 'religions' to get the list of available choices.
            person_a_email: (Required) Filer person email. By default it's an empty string.
            person_a_phone_number: (Required) Filer person phone number. By default it's an empty string.
            person_a_website: (Optional) Filer person website.
            person_a_idnr: (Required) Filer person tax ID number. German format. Example: 79 538 461 449.
            person_b_same_address: (Required) Whether spouse has same address.
            moved_from_other_german_city: (Required) Whether person moved from other German city. You should ask the user.
            person_b_gender: (Required if civil_status not '001') Spouse gender code. Use get_tax_registration_choices 'genders' to get the list of available choices.
            person_b_last_name: (Required if civil_status not '001') Spouse last name.
            person_b_first_name: (Required if civil_status not '001') Spouse first name.
            person_b_birth_name: (Optional) Spouse birth name. Only if civil_status not '001'.
            person_b_current_profession: (Optional) Spouse current profession in German. Only if civil_status not '001'.
            person_b_dob: (Required if civil_status not '001') Spouse date of birth (YYYY-MM-DD).
            person_b_street: (Required if civil_status not '001' and person_b_same_address is False) Spouse residence street name.
            person_b_house_number: (Required if civil_status not '001' and person_b_same_address is False) Spouse residence house number.
            person_b_apartment_number: (Optional) Spouse residence apartment number. Only if civil_status not '001' and person_b_same_address is False.
            person_b_address_ext: (Optional) Spouse residence address additional info. Only if civil_status not '001' and person_b_same_address is False.
            person_b_city: (Required if civil_status not '001' and person_b_same_address is False) Spouse residence city name.
            person_b_post_code: (Required if civil_status not '001' and person_b_same_address is False) Spouse residence post code.
            person_b_idnr: (Optional) Spouse tax ID number. German format. Example: 79 538 461 449. Only if civil_status not '001'. Trim whitespaces.
            person_b_religion: (Required if civil_status not '001') Spouse religion code. Use get_tax_registration_choices 'religions' to get the list of available choices.
            person_a_other_city_moving_date: (Required if moved_from_other_german_city is True) Date when person moved from other German city (YYYY-MM-DD).
            person_a_other_city_moving_street: (Optional) Person moved from other German city street name. Only if moved_from_other_german_city is True.
            person_a_other_city_moving_house_number: (Optional) Person moved from other German city house number. Only if moved_from_other_german_city is True.
            person_a_other_city_moving_apartment_number: (Optional) Person moved from other German city apartment number. Only if moved_from_other_german_city is True.
            person_a_other_city_moving_address_ext: (Optional) Person moved from other German city address additional info. Only if moved_from_other_german_city is True.
            person_a_other_city_moving_city: (Required if moved_from_other_german_city is True) Person moved from other German city city name.
            person_a_other_city_moving_post_code: (Required if moved_from_other_german_city is True) Person moved from other German city post code.
            
        Returns:
            Created tax registration data. Save the public_id from the response and proceed with the next steps using update_tax_registration.
        """
        api = ctx.request_context.lifespan_context.get("api")
        registration_url = urljoin(config.api_base_url, "api/v1/tax-registration/")
        
        # Generate UUID if not provided
        external_user_id = str(uuid.uuid4())
 
        # Create base payload
        payload = {
            "step": 1,
            "source": NORMAN_AGENT_SOURCE,
            "externalUserId": external_user_id,
            "locale": locale,
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
        public_id: str = Field(description="Public ID of the tax registration to update.  Get it from create_tax_registration. Always include it. It can't be empty."),
        session_key: str = Field(description="Session key of the tax registration to update. Get it from create_tax_registration. Always include it. It can't be empty."),
        external_user_id: str = Field(description="External user ID of the tax registration to update. Get it from create_tax_registration. Always include it. It can't be empty."),
        step: int = Field(description="Step of the tax registration to update. Use 2 for step 2, 3 for step 3, etc. The last step is 6. Always include it."),
        # Step 2 fields - Business Info
        profession_description: str = Field(default="", description="(Step 2) Description of your profession/business activity, required, max 200 chars"),
        business_started_activity_date: str = Field(default=None, description="(Step 2) Business started activity date (YYYY-MM-DD). By default it's today's date."),
        business_has_separated_office: bool = Field(default=False, description="(Step 2) Whether business has a separate office from home address"),
        business_office_street: Optional[str] = Field(default=None, description="(Step 2) Business office street name, required if business_has_separated_office=True"),
        business_office_house_number: Optional[str] = Field(default=None, description="(Step 2) Business office house number, required if business_has_separated_office=True"),
        business_office_apartment_number: Optional[str] = Field(default=None, description="(Step 2) Business office apartment number. Required if business_has_separated_office=True."),
        business_office_address_ext: Optional[str] = Field(default=None, description="(Step 2) Business office address additional info. Required if business_has_separated_office=True."),
        business_office_city: Optional[str] = Field(default=None, description="(Step 2) Business office city, required if business_has_separated_office=True"),
        business_office_post_code: Optional[str] = Field(default=None, description="(Step 2) Business office postal code, required if business_has_separated_office=True"),
        has_separated_email: bool = Field(default=False, description="(Step 2) Whether business has a separate email from personal email"),
        business_email: Optional[str] = Field(default="", description="(Step 2) Business email, required if has_separated_email=True"),
        business_website: str = Field(default="", description="(Step 2) Business website URL"),
        has_previous_business_in_germany: bool = Field(default=False, description="(Step 2) Whether you had a previous business in Germany"),
        previous_business_in_germany_activity: Optional[str] = Field(default="", description="(Step 2) Previous business activity description, max 199 chars, required if has_previous_business_in_germany=True"),
        previous_business_in_germany_city: Optional[str] = Field(default=None, description="(Step 2) Previous business city, required if has_previous_business_in_germany=True"),
        previous_business_in_germany_tax_number_state: Optional[str] = Field(default=None, description="(Step 2) Previous business tax number state, required if has_previous_business_in_germany=True. Use get_tax_registration_choices 'tax-states' to get the list of available choices."),
        previous_business_in_germany_tax_number: Optional[str] = Field(default=None, description="(Step 2) Previous business tax number, required if has_previous_business_in_germany=True. German format. Example: 39/396/97918"),
        previous_business_in_germany_from_date: Optional[str] = Field(default=None, description="(Step 2) Previous business start date (YYYY-MM-DD)"),
        previous_business_in_germany_to_date: Optional[str] = Field(default=None, description="(Step 2) Previous business end date (YYYY-MM-DD)"),
        previous_business_in_germany_vat_number: Optional[str] = Field(default=None, description="(Step 2) Previous business VAT number, must be in format DE followed by 9 digits"),
        # Step 3 fields - Tax Setup
        have_already_tax_number: bool = Field(default=False, description="(Step 3) Whether you already have a tax number"),
        previous_tax_number_state: Optional[str] = Field(default=None, description="(Step 3) Previous tax number state, required if have_already_tax_number=True. Use get_tax_registration_choices 'tax-states' to get the list of available choices."),
        previous_tax_number: Optional[str] = Field(default=None, description="(Step 3) Previous tax number (11-13 chars), required if have_already_tax_number=True. German format. Example: 39/396/97918"),
        profit_determination_method: Optional[str] = Field(default="01", description="(Step 3) Profit determination method (01=Single entry bookkeeping, 02=Double entry bookkeeping)"),
        estimated_revenue_for_current_year: int = Field(default=None, description="(Step 3) Estimated revenue for current year. Should be greater than 0."),
        estimated_revenue_for_next_year: int = Field(default=None, description="(Step 3) Estimated revenue for next year. Should be greater than 0."),
        kleinunternehmer_charge_vat: Optional[bool] = Field(default=False, description="(Step 3) Whether you charge VAT as a small business owner (Kleinunternehmer). Required if user is eligible for kleinunternehmer status."),
        need_vat_number: bool = Field(default=None, description="(Step 3) Whether you need a VAT number"),
        income_taxation_method: Optional[str] = Field(default="Istversteuerung", description="(Step 3) Income taxation method (Istversteuerung=Actual, Sollversteuerung=Target)"),
        vat_exemption_eligibility: Optional[bool] = Field(default=False, description="(Step 3) Whether eligible for VAT exemption"),
        vat_exemption_eligibility_activity_description: Optional[str] = Field(default=None, description="(Step 3) VAT exemption activity description, max 200 chars"),
        vat_exemption_eligibility_paragraph: Optional[str] = Field(default=None, description="(Step 3) VAT exemption paragraph, max 3 chars"),
        vat_reduction_on_sale_eligibility: Optional[bool] = Field(default=False, description="(Step 3) Whether eligible for VAT reduction on sales"),
        vat_reduction_on_sale_eligibility_activity_description: Optional[str] = Field(default=None, description="(Step 3) VAT reduction activity description, max 200 chars"),
        vat_reduction_on_sale_eligibility_paragraph: Optional[str] = Field(default=None, description="(Step 3) VAT reduction paragraph, max 3 chars"),
        # Step 4 fields - Tax Estimation
        is_spouse: Optional[bool] = Field(default=None, description="(Step 4) Whether you have a spouse (derived from civil_status)"),
        # Freelancing profit
        person_a_expected_profit_freelancing_for_current_year: str = Field(default=None, description="(Step 4) Your expected profit from freelancing for current year"),
        person_a_expected_profit_freelancing_for_next_year: str = Field(default=None, description="(Step 4) Your expected profit from freelancing for next year"),
        person_b_expected_profit_freelancing_for_current_year: Optional[str] = Field(default=None, description="(Step 4) Your spouse's expected profit from freelancing for current year. Required if is_spouse=True"),
        person_b_expected_profit_freelancing_for_next_year: Optional[str] = Field(default=None, description="(Step 4) Your spouse's expected profit from freelancing for next year. Required if is_spouse=True    "),
        # Commercial profit
        person_a_expected_profit_commercial_for_current_year: str = Field(default=None, description="(Step 4) Your expected profit from commercial operations for current year"),
        person_a_expected_profit_commercial_for_next_year: str = Field(default=None, description="(Step 4) Your expected profit from commercial operations for next year"),
        person_b_expected_profit_commercial_for_current_year: Optional[str] = Field(default=None, description="(Step 4) Your spouse's expected profit from commercial operations for current year. Required if is_spouse=True"),
        person_b_expected_profit_commercial_for_next_year: Optional[str] = Field(default=None, description="(Step 4) Your spouse's expected profit from commercial operations for next year. Required if is_spouse=True"),
        # Salary income
        person_a_expected_income_salary_for_current_year: str = Field(default=None, description="(Step 4) Your expected income from salary for current year"),
        person_a_expected_income_salary_for_next_year: str = Field(default=None, description="(Step 4) Your expected income from salary for next year"),
        person_b_expected_income_salary_for_current_year: Optional[str] = Field(default=None, description="(Step 4) Your spouse's expected income from salary for current year. Required if is_spouse=True"),
        person_b_expected_income_salary_for_next_year: Optional[str] = Field(default=None, description="(Step 4) Your spouse's expected income from salary for next year. Required if is_spouse=True"),  
        estimated_vat_pay_current_year: str = Field(default=None, description="(Step 4) Estimated VAT to pay in the current year, required"),
        # Step 5 fields - Bank Account
        has_separate_business_bank_account: bool = Field(default=False, description="(Step 5) Whether you have a separate business bank account"),
        business_bank_account_iban: Optional[str] = Field(default=None, description="(Step 5) Business bank account IBAN, required if has_separate_business_bank_account=True"),
        business_bank_account_owner: str = Field(default="1", description="(Step 5) Business bank account owner (1=taxpayer, 2=spouse, 3=taxpayer with spouse, 99=different person)"),
        business_bank_account_separate_owner_name: Optional[str] = Field(default=None, description="(Step 5) Business bank account separate owner name, required if business_bank_account_owner=99"),
        private_bank_account_iban: Optional[str] = Field(default=None, description="(Step 5) Private bank account IBAN"),
        private_bank_account_owner: str = Field(default="1", description="(Step 5) Private bank account owner (1=taxpayer, 2=spouse, 3=taxpayer with spouse, 99=different person)"),
        private_bank_account_owner_name: Optional[str] = Field(default=None, description="(Step 5) Private bank account owner name, required if private_bank_account_owner=99"),
        # Step 6 fields - Review and Submit
        tax_office: str = Field(default=None, description="(Step 6) Tax office code (4 digits), required")
    ) -> Dict[str, Any]:
        """
        Update a tax registration. Use this tool to continue with the next step of the tax registration process from 2 to 6.
        You need to provide the public_id from the response of create_tax_registration and go through the steps one by one.
        Each step has its own fields:

        Step 2 - Business Info:
        - professionDescription (string, required, max 200 chars): Description of your profession/business activity
        - businessStartedActivityDate (string in YYYY-MM-DD format): When business started activity
        - businessHasSeparatedOffice (boolean): Whether business has an office different from personal address
        - businessOfficeStreet (string): Business office street name (if separate office)
        - businessOfficeHouseNumber (string): Business office house number (if separate office)
        - businessOfficeApartmentNumber (string): Business office apartment number (if separate office)
        - businessOfficeAddressExt (string): Business office address additional info (if separate office)
        - businessOfficeCity (string): Business office city (if separate office)
        - businessOfficePostCode (string): Business office post code (if separate office)
        - hasSeparatedEmail (boolean): Whether business has a separate email
        - businessEmail (string): Business email address (if has separate email)
        - businessWebsite (string): Business website URL
        - hasPreviousBusinessInGermany (boolean): Whether previously had business in Germany
        - previousBusinessInGermanyActivity (string, max 199 chars): Previous business activity description
        - previousBusinessInGermanyCity (string): Previous business city
        - previousBusinessInGermanyTaxNumberState (string): State for previous business tax number
        - previousBusinessInGermanyTaxNumber (string): Previous business tax number
        - previousBusinessInGermanyFromDate (string in YYYY-MM-DD format): Previous business start date
        - previousBusinessInGermanyToDate (string in YYYY-MM-DD format): Previous business end date
        - previousBusinessInGermanyVatNumber (string): Previous business VAT number (must be in format DE followed by 9 digits)
        Step 3 - Tax Setup:
        - haveAlreadyTaxNumber (boolean, required): Whether you already have a tax number
        - previousTaxNumberState (string): State for previous tax number (required if filed returns). Use get_tax_registration_choices 'tax-states' to get the list of available choices.
        - previousTaxNumber (string): Previous tax number (11-13 chars, required if filed returns). German format. Example: 39/396/97918
        - profitDeterminationMethod (string): Method used (01=Single entry bookkeeping, 02=Double entry bookkeeping)
        - estimatedRevenueForCurrentYear (number, required): Estimated revenue for current year
        - estimatedRevenueForNextYear (number, required): Estimated revenue for next year
        - kleinunternehmerChargeVat (boolean): Whether charging VAT as a small business owner. Required if user is eligible for kleinunternehmer status.
        - needVatNumber (boolean, required): Whether you need a VAT number
        - incomeTaxationMethod (string): Income taxation method (Istversteuerung=Actual, Sollversteuerung=Target). Default: Istversteuerung
        - vatExemptionEligibility (boolean): Whether eligible for VAT exemption. Only if user is not eligible for kleinunternehmer status.
        - vatExemptionEligibilityActivityDescription (string, max 200 chars): VAT exemption activity description. Only if user is not eligible for kleinunternehmer status.
        - vatExemptionEligibilityParagraph (string, max 3 chars): VAT exemption paragraph. Only if user is not eligible for kleinunternehmer status.
        - vatReductionOnSaleEligibility (boolean): Whether eligible for VAT reduction on sale. Only if user is not eligible for kleinunternehmer status.
        - vatReductionOnSaleEligibilityActivityDescription (string, max 200 chars): VAT reduction activity description. Only if user is not eligible for kleinunternehmer status.
        - vatReductionOnSaleEligibilityParagraph (string, max 3 chars): VAT reduction paragraph. Only if user is not eligible for kleinunternehmer status.
            For step 3, you should ask first the following fields: businessStartedActivityDate (from step 2), estimatedRevenueForCurrentYear and estimatedRevenueForNextYear. 
            
            To determine if the user is eligible for kleinunternehmer (small business owner) status, use this logic:
            1. Get the business founding date (businessStartedActivityDate from step 2)
            2. Calculate the current year from the founding date or use the current year if not available
            3. The revenue limit is €25,000 for 2025, €22,000 for other years
            4. Calculate working months in the first year (12 - founding month)
            5. Calculate monthly estimated revenue (estimatedRevenueForCurrentYear / working months)
            6. Calculate full year equivalent revenue (monthly estimated * 12)
            7. User is eligible for kleinunternehmer if full year equivalent revenue <= limit
            
            Explain this calculation to the user and advise them on their eligibility for kleinunternehmer status.
            If user is eligible for kleinunternehmer status, always ask them if they want to charge VAT as a small business owner: kleinunternehmer_charge_vat

        Step 4 - Tax Estimation:
        - estimatedVatProfile (number): Estimated VAT profile
        - isSpouse (boolean): Whether you have a spouse (automatically determined from step 1)
        - estimatedVatPayCurrentYear (string, required): Estimated VAT to pay in current year

        For income/profit estimations, each category follows this pattern:
        - isExpectedProfitCATEGORYForCurrentYear (boolean): Whether you expect profit from CATEGORY
        - isPersonBExpectedProfitCATEGORYForCurrentYear (boolean): Whether spouse expects profit from CATEGORY
        - personAExpectedProfitCATEGORYForCurrentYear (string): Your expected profit from CATEGORY for current year
        - personAExpectedProfitCATEGORYForNextYear (string): Your expected profit from CATEGORY for next year
        - personBExpectedProfitCATEGORYForCurrentYear (string): Spouse's expected profit from CATEGORY for current year
        - personBExpectedProfitCATEGORYForNextYear (string): Spouse's expected profit from CATEGORY for next year
        
        Categories include:
        - Freelancing: for self-employed/freelance work
        - Commercial: for commercial business operations
        - Salary: for employment income

        Step 5 - Bank Account:
        - hasSeparateBusinessBankAccount (boolean, required): Whether you have a separate business bank account
        - businessBankAccountIban (string): Business bank account IBAN (required if has separate account). Delete whitespace and dashes.
        - businessBankAccountOwner (string): Business bank account owner (required if has separate account)
          Options: 1=taxpayer, 2=spouse, 3=taxpayer with spouse, 99=different person
        - businessBankAccountSeparateOwnerName (string): Name if owner is not taxpayer or spouse. Required businessBankAccoountOwner is 99
        - privateBankAccountIban (string): Private bank account IBAN. Delete whitespace and dashes.
        - privateBankAccountOwner (string, required): Private bank account owner
          Options: 1=taxpayer, 2=spouse, 3=taxpayer with spouse, 99=different person
        - privateBankAccountOwnerName (string): Name if owner is not taxpayer or spouse. Required privateBankAccountOwner is 99

        Step 6 - Review and Submit:
        - taxOffice (string, required): Tax office code (4 digits)
            For step 6, use the get_tax_offices tool to find the appropriate tax office code using the city name. Always double check the tax office with the user before moving on.
            You can search for tax offices by city name.
          
        Args:
            public_id: Public ID of the tax registration to update
            external_user_id: External user ID. You should get this from the tax registration form data.
            session_key: Session key. You should get this from the tax registration form data.
            step: Registration step (1-6)
            ... various fields depending on the step
            
        Returns:
            Updated tax registration data. After step 6, we should generate_registration_preview and show the preview to the user.
        """

        api = ctx.request_context.lifespan_context.get("api")

        registration_url = urljoin(config.api_base_url, f"api/v1/tax-registration/{public_id}/")
        
        # Create payload with all provided fields
        payload = {
            "step": step,
            "publicId": public_id,
            "source": NORMAN_AGENT_SOURCE,
            "externalUserId": external_user_id,
            "sessionKey": session_key,
        }

        if step == 2:
            payload["professionFoundingArticle"] = "1"
            payload["professionDescription"] = profession_description
            payload["businessStartedActivityDate"] = business_started_activity_date
            payload["businessHasSeparatedOffice"] = business_has_separated_office
            payload["businessOfficeStreet"] = business_office_street or ""
            payload["businessOfficeHouseNumber"] = business_office_house_number or ""
            payload["businessOfficeApartmentNumber"] = business_office_apartment_number or ""
            payload["businessOfficeAddressExt"] = business_office_address_ext or ""
            payload["businessOfficeCity"] = business_office_city or ""
            payload["businessOfficePostCode"] = business_office_post_code or ""
            payload["hasSeparatedEmail"] = has_separated_email
            payload["businessEmail"] = business_email or ""
            payload["businessWebsite"] = business_website or ""
            payload["hasPreviousBusinessInGermany"] = has_previous_business_in_germany
            payload["previousBusinessInGermanyActivity"] = previous_business_in_germany_activity or ""
            payload["previousBusinessInGermanyCity"] = previous_business_in_germany_city or ""
            payload["previousBusinessInGermanyTaxNumberState"] = previous_business_in_germany_tax_number_state or "berlin"
            payload["previousBusinessInGermanyTaxNumber"] = previous_business_in_germany_tax_number or ""
            payload["previousBusinessInGermanyFromDate"] = previous_business_in_germany_from_date
            payload["previousBusinessInGermanyToDate"] = previous_business_in_germany_to_date
            payload["previousBusinessInGermanyVatNumber"] = previous_business_in_germany_vat_number or ""
        
        if step == 3:
            payload["haveAlreadyTaxNumber"] = have_already_tax_number
            payload["previousTaxNumberState"] = previous_tax_number_state or ""
            payload["previousTaxNumber"] = previous_tax_number or ""
            payload["profitDeterminationMethod"] = profit_determination_method
            payload["estimatedRevenueForCurrentYear"] = estimated_revenue_for_current_year
            payload["estimatedRevenueForNextYear"] = estimated_revenue_for_next_year
            payload["kleinunternehmerChargeVat"] = kleinunternehmer_charge_vat
            payload["needVatNumber"] = need_vat_number
            payload["incomeTaxationMethod"] = income_taxation_method
            payload["vatExemptionEligibility"] = vat_exemption_eligibility
            payload["vatExemptionEligibilityActivityDescription"] = vat_exemption_eligibility_activity_description or ""
            payload["vatExemptionEligibilityParagraph"] = vat_exemption_eligibility_paragraph or ""
            payload["vatReductionOnSaleEligibility"] = vat_reduction_on_sale_eligibility
            payload["vatReductionOnSaleEligibilityActivityDescription"] = vat_reduction_on_sale_eligibility_activity_description or ""
            payload["vatReductionOnSaleEligibilityParagraph"] = vat_reduction_on_sale_eligibility_paragraph or ""

        
        if step == 4:
            payload["estimatedVatProfile"] = 1
            payload["estimatedVatPayCurrentYear"] = estimated_vat_pay_current_year or "0.00"
            payload["personAExpectedProfitFreelancingForCurrentYear"] = person_a_expected_profit_freelancing_for_current_year or "0.00"
            payload["personAExpectedProfitFreelancingForNextYear"] = person_a_expected_profit_freelancing_for_next_year or "0.00"
            payload["personAExpectedProfitCommercialForCurrentYear"] = person_a_expected_profit_commercial_for_current_year or "0.00"
            payload["personAExpectedProfitCommercialForNextYear"] = person_a_expected_profit_commercial_for_next_year or "0.00"
            payload["personAExpectedIncomeSalaryForCurrentYear"] = person_a_expected_income_salary_for_current_year or "0.00"
            payload["personAExpectedIncomeSalaryForNextYear"] = person_a_expected_income_salary_for_next_year or 0
            payload["personAExpectedProfitInvestmentsForCurrentYear"] = "0.00" 
            payload["personAExpectedProfitInvestmentsForNextYear"] = "0.00"
            payload["personAExpectedProfitRentalAndLeasingForCurrentYear"] = "0.00" 
            payload["personAExpectedProfitRentalAndLeasingForNextYear"] = "0.00" 
            
            if is_spouse:
                payload["personBExpectedProfitFreelancingForCurrentYear"] = person_b_expected_profit_freelancing_for_current_year or "0.00"
                payload["personBExpectedProfitFreelancingForNextYear"] = person_b_expected_profit_freelancing_for_next_year or "0.00"
                payload["personBExpectedProfitCommercialForCurrentYear"] = person_b_expected_profit_commercial_for_current_year or "0.00"
                payload["personBExpectedProfitCommercialForNextYear"] = person_b_expected_profit_commercial_for_next_year or "0.00"
                payload["personBExpectedIncomeSalaryForCurrentYear"] = person_b_expected_income_salary_for_current_year or "0.00"
                payload["personBExpectedIncomeSalaryForNextYear"] = person_b_expected_income_salary_for_next_year or "0.00"
                payload["personBExpectedProfitInvestmentsForCurrentYear"] = "0.00" 
                payload["personBExpectedProfitInvestmentsForNextYear"] = "0.00"
                payload["personBExpectedProfitRentalAndLeasingForCurrentYear"] = "0.00" 
                payload["personBExpectedProfitRentalAndLeasingForNextYear"] = "0.00"

        if step == 5:
            payload["hasSeparateBusinessBankAccount"] = has_separate_business_bank_account
            payload["businessBankAccountOwner"] = business_bank_account_owner
            payload["businessBankAccountSeparateOwnerName"] = business_bank_account_separate_owner_name or ""
            payload["businessBankAccountIban"] = business_bank_account_iban or ""
            payload["privateBankAccountIban"] = private_bank_account_iban or ""
            payload["privateBankAccountOwner"] = private_bank_account_owner
            payload["privateBankAccountOwnerName"] = private_bank_account_owner_name or ""
        
        if step == 6:
            payload["taxOffice"] = tax_office
        
        return api._make_request("PATCH", registration_url, json_data=payload, skip_auth=True)
    
    
    @mcp.tool()
    async def get_tax_registration(
        ctx: Context,
        session_key: Optional[str] = Field(default=None, description="Session key. You should get it from tax registration form data."),
    ) -> Dict[str, Any]:
        """
        Get a tax registration form data. You should get session_key from tax registration form data.
        
        Args:
            session_key: Session key. You should get it from tax registration form data.
            
        Returns:
            Tax registration data
        """
        api = ctx.request_context.lifespan_context.get("api")
        company_id = api.company_id
        registration_url = urljoin(config.api_base_url, "api/v1/tax-registration/my/")

        if company_id:
            params = {}
        else:
            params = {"sessionKey": session_key}
        
        return api._make_request("GET", registration_url, params=params, skip_auth=True)
    
    @mcp.tool()
    async def generate_registration_preview(
        ctx: Context,
        public_id: str = Field(description="Public ID of the tax registration form to generate preview for")
    ) -> Image:
        """
        Generate a preview of the tax registration and return it as an image.
        
        Args:
            public_id: Public ID of the tax registration
            
        Returns:
            Tax registration preview as an image
        """
        api = ctx.request_context.lifespan_context.get("api")

        preview_url = urljoin(config.api_base_url, f"api/v1/tax-registration/{public_id}/preview/")
        
        try:
            # response = requests.post(
            #     preview_url,
            #     timeout=config.NORMAN_API_TIMEOUT
            # )
            # response.raise_for_status()

            response = api._make_request("POST", preview_url, skip_auth=True)
            
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
        params = {"externalUserId": external_user_id}
        
        return api._make_request("GET", check_url, params=params, skip_auth=True)
