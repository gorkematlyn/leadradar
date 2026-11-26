"""All ORM models; importing this package registers them on ``Base.metadata``."""

from leadradar.db.models.advertising import (  # noqa: F401
    AdvertisingProvider,
    AdvertisingResearchRun,
    Advertisement,
    Advertiser,
    ApifyActorConfig,
    ProviderUsage,
)
from leadradar.db.models.audit import (  # noqa: F401
    AuditFinding,
    AuditRule,
    Evidence,
    EvidenceBlob,
    TrackingDetection,
    TrackingTechnology,
    WebsiteAudit,
    WebsiteProperty,
)
from leadradar.db.models.auth import (  # noqa: F401
    ActivityLog,
    LoginAttempt,
    RateLimitBucket,
    RecoveryCode,
    User,
    UserPreference,
    UserSession,
)
from leadradar.db.models.catalog import (  # noqa: F401
    ApplicationSetting,
    Country,
    ImportRun,
    Industry,
    IndustryRule,
    Region,
    SavedGeoSelection,
)
from leadradar.db.models.company import (  # noqa: F401
    ChangeEvent,
    Company,
    CompanyChange,
    CompanyLocation,
    CompanySnapshot,
    CompanySource,
    CompanyTag,
    Contact,
    CrmActivity,
    CrmStatus,
    DuplicateCandidate,
    MergeHistory,
    SocialProfile,
    SuppressionEntry,
    Tag,
)
from leadradar.db.models.reports import Report, ReportAccessToken, ReportAsset, ReportTemplate, ReportVersion  # noqa: F401
from leadradar.db.models.scoring import (  # noqa: F401
    LeadScore,
    ReviewQuestion,
    ReviewResponse,
    ReviewTemplate,
    ScoreOverride,
    ScoringProfile,
    ScoringRule,
    ServiceRule,
    ServiceScore,
)
from leadradar.db.models.system import (  # noqa: F401
    CampaignRun,
    Job,
    JobAttempt,
    JobLog,
    Notification,
    RetentionPolicy,
    SavedCampaign,
    SavedFilter,
    SchedulerLock,
    WorkerHeartbeat,
)
