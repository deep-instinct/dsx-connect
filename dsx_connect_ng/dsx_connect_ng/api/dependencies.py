from fastapi import HTTPException, Request, status

from dsx_connect_ng.control_plane.service import ControlPlaneService


def get_control_plane_service(request: Request) -> ControlPlaneService:
    service = getattr(request.app.state, "control_plane_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="control_plane_service_unavailable",
        )
    return service
