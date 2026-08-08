"""API monitor CRUD, manual checks, and check history."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from apps.api.app.core.dependencies import (
    get_api_monitor_service,
    get_monitor_check_service,
)
from apps.api.app.monitoring.service import ApiMonitorService, MonitorCheckService
from apps.api.app.schemas.monitor import (
    MonitorCheckResponse,
    MonitorCreateRequest,
    MonitorResponse,
    MonitorUpdateRequest,
)

router = APIRouter(prefix="/monitors", tags=["monitors"])


@router.post("", response_model=MonitorResponse, status_code=status.HTTP_201_CREATED)
async def create_monitor(
    request: MonitorCreateRequest,
    service: Annotated[ApiMonitorService, Depends(get_api_monitor_service)],
) -> MonitorResponse:
    return await service.create(request)


@router.get("", response_model=list[MonitorResponse])
def list_monitors(
    service: Annotated[ApiMonitorService, Depends(get_api_monitor_service)],
) -> list[MonitorResponse]:
    return service.list()


@router.get("/{monitor_id}", response_model=MonitorResponse)
def get_monitor(
    monitor_id: str,
    service: Annotated[ApiMonitorService, Depends(get_api_monitor_service)],
) -> MonitorResponse:
    return service.get(monitor_id)


@router.patch("/{monitor_id}", response_model=MonitorResponse)
async def update_monitor(
    monitor_id: str,
    request: MonitorUpdateRequest,
    service: Annotated[ApiMonitorService, Depends(get_api_monitor_service)],
) -> MonitorResponse:
    return await service.update(monitor_id, request)


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_monitor(
    monitor_id: str,
    service: Annotated[ApiMonitorService, Depends(get_api_monitor_service)],
) -> Response:
    service.delete(monitor_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{monitor_id}/check", response_model=MonitorCheckResponse)
async def check_monitor(
    monitor_id: str,
    service: Annotated[MonitorCheckService, Depends(get_monitor_check_service)],
) -> MonitorCheckResponse:
    return await service.check(monitor_id)


@router.get("/{monitor_id}/checks", response_model=list[MonitorCheckResponse])
def list_monitor_checks(
    monitor_id: str,
    service: Annotated[MonitorCheckService, Depends(get_monitor_check_service)],
) -> list[MonitorCheckResponse]:
    return service.list_checks(monitor_id)
