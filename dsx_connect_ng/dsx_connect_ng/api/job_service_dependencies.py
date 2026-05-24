from fastapi import HTTPException, Request, status

from dsx_connect_ng.jobs.service import JobService


def get_job_service(request: Request) -> JobService:
    service = getattr(request.app.state, "job_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="job_service_unavailable",
        )
    return service
