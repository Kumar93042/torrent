from fastapi import FastAPI, APIRouter, UploadFile, File, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timedelta
import libtorrent as lt
import asyncio
import json
import aiofiles
import shutil
from concurrent.futures import ThreadPoolExecutor
import threading
import time

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Global torrent session with better configuration
ses = lt.session()

# Configure session settings for better downloading
settings = ses.get_settings()
settings['enable_dht'] = True
settings['enable_lsd'] = True  # Local Service Discovery
settings['enable_upnp'] = True
settings['enable_natpmp'] = True
settings['announce_to_all_tiers'] = True
settings['announce_to_all_trackers'] = True
settings['auto_manage_startup'] = True
settings['auto_manage_interval'] = 30
settings['max_connections'] = 200
settings['max_uploads'] = 10
settings['download_rate_limit'] = 0  # Unlimited by default
settings['upload_rate_limit'] = 0    # Unlimited by default

# Apply settings
ses.apply_settings(settings)

# Listen on ports
ses.listen_on(6881, 6891)

# Add DHT routers for better peer discovery
ses.add_dht_router('router.bittorrent.com', 6881)
ses.add_dht_router('dht.transmissionbt.com', 6881)
ses.add_dht_router('router.utorrent.com', 6881)

# Global state for managing torrents
torrent_handles: Dict[str, Any] = {}
download_stats: Dict[str, Dict] = {}
websocket_connections: List[WebSocket] = []
executor = ThreadPoolExecutor(max_workers=4)

# Download directory
DOWNLOAD_DIR = Path("d")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Models
class TorrentCreate(BaseModel):
    name: str
    download_speed_limit: Optional[int] = None  # bytes per second
    upload_speed_limit: Optional[int] = None
    scheduled_start: Optional[datetime] = None

class TorrentInfo(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    size: int
    progress: float = 0.0
    download_rate: float = 0.0
    upload_rate: float = 0.0
    eta: Optional[str] = None
    status: str = "queued"  # queued, downloading, paused, completed, error
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    file_path: Optional[str] = None
    download_speed_limit: Optional[int] = None
    upload_speed_limit: Optional[int] = None
    scheduled_start: Optional[datetime] = None

class TorrentUpdate(BaseModel):
    download_speed_limit: Optional[int] = None
    upload_speed_limit: Optional[int] = None
    scheduled_start: Optional[datetime] = None

class SystemStats(BaseModel):
    total_downloads: int
    active_downloads: int
    completed_downloads: int
    total_downloaded: int
    total_uploaded: int
    global_download_rate: float
    global_upload_rate: float

# Background task for monitoring torrents with better state handling
async def monitor_torrents():
    while True:
        try:
            for torrent_id, handle in list(torrent_handles.items()):
                if not handle.is_valid():
                    logger.warning(f"Invalid handle for torrent {torrent_id}, removing")
                    del torrent_handles[torrent_id]
                    continue
                    
                status = handle.status()
                
                # Update download stats
                stats = {
                    'progress': status.progress * 100,
                    'download_rate': status.download_rate,
                    'upload_rate': status.upload_rate,
                    'state': str(status.state),
                    'total_download': status.total_download,
                    'total_upload': status.total_upload,
                    'num_peers': status.num_peers,
                    'num_seeds': status.num_seeds,
                    'error': status.error if status.error else None
                }
                
                download_stats[torrent_id] = stats
                
                # Log errors if any
                if status.error:
                    logger.error(f"Torrent {torrent_id} error: {status.error}")
                
                # Calculate ETA
                if stats['download_rate'] > 0:
                    remaining_bytes = status.total_wanted - status.total_download
                    eta_seconds = remaining_bytes / stats['download_rate']
                    stats['eta'] = str(timedelta(seconds=int(eta_seconds)))
                else:
                    stats['eta'] = "Unknown"
                
                # Determine status more accurately
                torrent_status = "downloading"
                if status.is_seeding:
                    torrent_status = "completed"
                elif status.paused:
                    torrent_status = "paused"
                elif status.state == lt.torrent_status.checking_files:
                    torrent_status = "checking"
                elif status.state == lt.torrent_status.downloading_metadata:
                    torrent_status = "downloading_metadata"
                elif status.state == lt.torrent_status.queued_for_checking:
                    torrent_status = "queued"
                elif status.error:
                    torrent_status = "error"
                
                # Update database with more detailed info
                await db.torrents.update_one(
                    {"id": torrent_id},
                    {"$set": {
                        "progress": stats['progress'],
                        "download_rate": stats['download_rate'],
                        "upload_rate": stats['upload_rate'],
                        "status": torrent_status,
                        "eta": stats['eta'],
                        "num_peers": stats['num_peers'],
                        "num_seeds": stats['num_seeds'],
                        "error": stats['error']
                    }}
                )
                
                # Mark as completed if finished
                if status.is_seeding and stats['progress'] >= 100:
                    await db.torrents.update_one(
                        {"id": torrent_id},
                        {"$set": {
                            "status": "completed",
                            "completed_at": datetime.utcnow()
                        }}
                    )
                    logger.info(f"Torrent {torrent_id} completed successfully")
                
                # Log progress for debugging
                if stats['progress'] > 0:
                    logger.info(f"Torrent {torrent_id}: {stats['progress']:.1f}% - "
                              f"D: {stats['download_rate']/1024:.1f} KB/s - "
                              f"Peers: {stats['num_peers']} - "
                              f"Seeds: {stats['num_seeds']}")
            
            # Send updates to websocket clients
            if websocket_connections:
                update_data = {
                    "type": "torrent_update",
                    "stats": download_stats
                }
                disconnected = []
                for ws in websocket_connections:
                    try:
                        await ws.send_text(json.dumps(update_data, default=str))
                    except:
                        disconnected.append(ws)
                
                # Remove disconnected websockets
                for ws in disconnected:
                    websocket_connections.remove(ws)
            
            await asyncio.sleep(2)  # Update every 2 seconds
            
        except Exception as e:
            logger.error(f"Error in monitor_torrents: {e}")
            await asyncio.sleep(5)

# Start monitoring task
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(monitor_torrents())

# WebSocket endpoint for real-time updates
@api_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    websocket_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_connections.remove(websocket)

# Helper function to add torrent with better configuration
def add_torrent_to_session(torrent_data: bytes, torrent_id: str, params: dict):
    try:
        info = lt.torrent_info(torrent_data)
        
        # Set download parameters with better configuration
        add_torrent_params = {
            'ti': info,
            'save_path': str(DOWNLOAD_DIR),
            'flags': (
                lt.torrent_flags.duplicate_is_error | 
                lt.torrent_flags.auto_managed |
                lt.torrent_flags.apply_ip_filter
            )
        }
        
        handle = ses.add_torrent(add_torrent_params)
        
        # Set speed limits if specified
        if params.get('download_speed_limit'):
            handle.set_download_limit(params['download_speed_limit'])
        if params.get('upload_speed_limit'):
            handle.set_upload_limit(params['upload_speed_limit'])
        
        # Force reannounce to find more peers
        handle.force_reannounce()
        
        # Pause if scheduled for later
        if params.get('scheduled_start') and params['scheduled_start'] > datetime.utcnow():
            handle.pause()
        
        torrent_handles[torrent_id] = handle
        logger.info(f"Successfully added torrent: {info.name()}")
        return True
        
    except Exception as e:
        logger.error(f"Error adding torrent: {e}")
        return False

# API Routes
@api_router.post("/torrents/upload", response_model=TorrentInfo)
async def upload_torrent(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    download_speed_limit: Optional[int] = None,
    upload_speed_limit: Optional[int] = None
):
    if not file.filename.endswith('.torrent'):
        raise HTTPException(status_code=400, detail="File must be a .torrent file")
    
    try:
        # Read torrent file
        torrent_data = await file.read()
        
        # Parse torrent info
        info = lt.torrent_info(torrent_data)
        torrent_id = str(uuid.uuid4())
        
        # Create torrent info object
        torrent_info = TorrentInfo(
            id=torrent_id,
            name=info.name(),
            size=info.total_size(),
            download_speed_limit=download_speed_limit,
            upload_speed_limit=upload_speed_limit
        )
        
        # Save to database
        await db.torrents.insert_one(torrent_info.dict())
        
        # Add to torrent session
        params = {
            'download_speed_limit': download_speed_limit,
            'upload_speed_limit': upload_speed_limit
        }
        
        success = await asyncio.get_event_loop().run_in_executor(
            executor, add_torrent_to_session, torrent_data, torrent_id, params
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to add torrent")
        
        return torrent_info
        
    except Exception as e:
        logger.error(f"Error uploading torrent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/torrents", response_model=List[TorrentInfo])
async def get_torrents():
    torrents = await db.torrents.find().sort("created_at", -1).to_list(1000)
    return [TorrentInfo(**torrent) for torrent in torrents]

@api_router.post("/torrents/{torrent_id}/pause")
async def pause_torrent(torrent_id: str):
    if torrent_id not in torrent_handles:
        raise HTTPException(status_code=404, detail="Torrent not found")
    
    handle = torrent_handles[torrent_id]
    handle.pause()
    
    await db.torrents.update_one(
        {"id": torrent_id},
        {"$set": {"status": "paused"}}
    )
    
    return {"message": "Torrent paused"}

@api_router.post("/torrents/{torrent_id}/resume")
async def resume_torrent(torrent_id: str):
    if torrent_id not in torrent_handles:
        raise HTTPException(status_code=404, detail="Torrent not found")
    
    handle = torrent_handles[torrent_id]
    handle.resume()
    
    await db.torrents.update_one(
        {"id": torrent_id},
        {"$set": {"status": "downloading"}}
    )
    
    return {"message": "Torrent resumed"}

@api_router.delete("/torrents/{torrent_id}")
async def delete_torrent(torrent_id: str):
    if torrent_id in torrent_handles:
        handle = torrent_handles[torrent_id]
        ses.remove_torrent(handle)
        del torrent_handles[torrent_id]
        
        if torrent_id in download_stats:
            del download_stats[torrent_id]
    
    await db.torrents.delete_one({"id": torrent_id})
    return {"message": "Torrent deleted"}

@api_router.put("/torrents/{torrent_id}")
async def update_torrent(torrent_id: str, update_data: TorrentUpdate):
    if torrent_id not in torrent_handles:
        raise HTTPException(status_code=404, detail="Torrent not found")
    
    handle = torrent_handles[torrent_id]
    
    # Update speed limits
    if update_data.download_speed_limit is not None:
        handle.set_download_limit(update_data.download_speed_limit)
    if update_data.upload_speed_limit is not None:
        handle.set_upload_limit(update_data.upload_speed_limit)
    
    # Update in database
    update_dict = {k: v for k, v in update_data.dict().items() if v is not None}
    if update_dict:
        await db.torrents.update_one(
            {"id": torrent_id},
            {"$set": update_dict}
        )
    
    return {"message": "Torrent updated"}

@api_router.get("/stats", response_model=SystemStats)
async def get_system_stats():
    total_downloads = await db.torrents.count_documents({})
    active_downloads = await db.torrents.count_documents({"status": {"$in": ["downloading", "queued"]}})
    completed_downloads = await db.torrents.count_documents({"status": "completed"})
    
    # Calculate totals
    pipeline = [
        {"$group": {
            "_id": None,
            "total_size": {"$sum": "$size"}
        }}
    ]
    
    result = await db.torrents.aggregate(pipeline).to_list(1)
    total_downloaded = result[0]["total_size"] if result else 0
    
    # Global rates
    global_download_rate = sum(stats.get('download_rate', 0) for stats in download_stats.values())
    global_upload_rate = sum(stats.get('upload_rate', 0) for stats in download_stats.values())
    
    return SystemStats(
        total_downloads=total_downloads,
        active_downloads=active_downloads,
        completed_downloads=completed_downloads,
        total_downloaded=total_downloaded,
        total_uploaded=0,  # Would need to track this separately
        global_download_rate=global_download_rate,
        global_upload_rate=global_upload_rate
    )

@api_router.post("/settings/global-limits")
async def set_global_limits(download_limit: Optional[int] = None, upload_limit: Optional[int] = None):
    settings = ses.get_settings()
    
    if download_limit is not None:
        settings['download_rate_limit'] = download_limit
    if upload_limit is not None:
        settings['upload_rate_limit'] = upload_limit
    
    ses.apply_settings(settings)
    return {"message": "Global limits updated"}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()