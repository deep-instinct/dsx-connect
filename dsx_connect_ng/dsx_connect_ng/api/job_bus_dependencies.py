from fastapi import HTTPException, Request, status

from dsx_connect_ng.jobs.bus import JobBus


def get_job_bus(request: Request) -> JobBus:
    bus = getattr(request.app.state, "job_bus", None)
    if bus is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="job_bus_unavailable",
        )
    return bus
