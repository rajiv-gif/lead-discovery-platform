# Import all models here so Base.metadata is fully populated
# before Alembic autogenerate or any create_all() call.
from src.models.campaign import Campaign
from src.models.company import Company
from src.models.discovery_hit import DiscoveryHit
from src.models.company_page import CompanyPage
from src.models.contact import Contact
from src.models.email import Email
from src.models.phone import Phone
from src.models.company_lead import CompanyLead
from src.models.audit_log import AuditLog
from src.models.suppression_list import SuppressionList

__all__ = [
    "Campaign",
    "Company",
    "DiscoveryHit",
    "CompanyPage",
    "Contact",
    "Email",
    "Phone",
    "CompanyLead",
    "AuditLog",
    "SuppressionList",
]
