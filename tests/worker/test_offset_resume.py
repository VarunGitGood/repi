import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from repi.worker import IngestionWorker
from repi.models.schema import WatcherConfig, WatcherOffset

@pytest.mark.asyncio
async def test_offset_resume(tmp_path):
    # Setup temp file with existing content and new content
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "app.log"
    
    old_content = "line 1\nline 2\n"
    new_content = "line 3\nline 4\n"
    log_file.write_text(old_content + new_content)
    
    old_size = len(old_content)
    
    # Mock Worker
    worker = IngestionWorker()
    config = WatcherConfig(
        id=uuid4(),
        service_name="test-service",
        watch_path=str(log_dir),
        enabled=True
    )
    worker.watcher_configs = {str(log_dir): config}
    
    # Mock Session and Ingestor
    # Mock Session and Ingestor
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_ingestor = AsyncMock()
    mock_ingestor.ingest = AsyncMock(return_value=2)
    
    worker.container.get_session = MagicMock(return_value=mock_session)
    worker.container.get_ingestor = MagicMock(return_value=mock_ingestor)
    
    # Mock existing offset in DB
    existing_offset = WatcherOffset(
        watcher_config_id=config.id,
        file_path=str(log_file),
        offset=old_size
    )
    
    mock_result = MagicMock()
    mock_result.first = MagicMock(side_effect=[
        existing_offset, # get_or_create_offset
        existing_offset  # update_offset
    ])
    mock_session.exec = AsyncMock(return_value=mock_result)
    
    # Run handler
    await worker.handle_file_change(str(log_file))
    
    # Assert ingestor called only with NEW content
    mock_ingestor.ingest.assert_called_once()
    args, _ = mock_ingestor.ingest.call_args
    assert args[0] == new_content
    
    # Assert offset updated to full file size
    assert worker.offsets[str(log_file)] == log_file.stat().st_size
