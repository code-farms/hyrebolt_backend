from app.sources.base import JobSourceConnector
from app.sources.connectors.company_careers import CompanyCareersConnector
from app.sources.connectors.cutshort import CutshortConnector
from app.sources.connectors.foundit import FounditConnector
from app.sources.connectors.indeed import IndeedConnector
from app.sources.connectors.instahyre import InstahyreConnector
from app.sources.connectors.linkedin import LinkedInConnector
from app.sources.connectors.naukri import NaukriConnector
from app.sources.connectors.remoteok import RemoteOkConnector
from app.sources.connectors.wellfound import WellfoundConnector
from app.sources.connectors.weworkremotely import WeWorkRemotelyConnector
from app.sources.connectors.ycombinator import YCombinatorConnector

# Keys must match JobSource.name in the DB seed exactly.
CONNECTOR_CLASSES: dict[str, type[JobSourceConnector]] = {
    "linkedin": LinkedInConnector,
    "naukri": NaukriConnector,
    "indeed": IndeedConnector,
    "cutshort": CutshortConnector,
    "wellfound": WellfoundConnector,
    "ycombinator": YCombinatorConnector,
    "instahyre": InstahyreConnector,
    "foundit": FounditConnector,
    "remoteok": RemoteOkConnector,
    "weworkremotely": WeWorkRemotelyConnector,
    "company_careers": CompanyCareersConnector,
}

__all__ = ["CONNECTOR_CLASSES"]
