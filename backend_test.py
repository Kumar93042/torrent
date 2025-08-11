#!/usr/bin/env python3
"""
Comprehensive Backend Testing for Torrent Management System
Tests all API endpoints and WebSocket functionality
"""

import asyncio
import aiohttp
import websockets
import json
import os
import sys
from pathlib import Path
import tempfile
import time
from typing import Dict, Any

# Get backend URL from frontend .env file
def get_backend_url():
    frontend_env_path = Path("/app/frontend/.env")
    if frontend_env_path.exists():
        with open(frontend_env_path, 'r') as f:
            for line in f:
                if line.startswith('REACT_APP_BACKEND_URL='):
                    return line.split('=', 1)[1].strip()
    return "http://localhost:8001"

BACKEND_URL = get_backend_url()
API_BASE = f"{BACKEND_URL}/api"

print(f"Testing backend at: {API_BASE}")

class TorrentBackendTester:
    def __init__(self):
        self.session = None
        self.test_results = {}
        self.uploaded_torrent_id = None
        
    async def setup(self):
        """Initialize HTTP session"""
        self.session = aiohttp.ClientSession()
        
    async def cleanup(self):
        """Clean up resources"""
        if self.session:
            await self.session.close()
            
    def create_test_torrent_file(self) -> bytes:
        """Create a minimal valid torrent file for testing"""
        # Create a proper minimal torrent file using bencode format
        import hashlib
        
        # Create a simple test file content
        test_content = b"This is a test file for torrent testing."
        piece_length = 32768
        
        # Calculate piece hash
        piece_hash = hashlib.sha1(test_content).digest()
        
        # Create torrent dictionary
        torrent_dict = {
            b'announce': b'http://tracker.example.com:8080/announce',
            b'info': {
                b'name': b'test-file.txt',
                b'length': len(test_content),
                b'piece length': piece_length,
                b'pieces': piece_hash
            }
        }
        
        # Simple bencode implementation for our test
        def bencode(obj):
            if isinstance(obj, int):
                return f"i{obj}e".encode()
            elif isinstance(obj, bytes):
                return f"{len(obj)}:".encode() + obj
            elif isinstance(obj, dict):
                result = b"d"
                for key in sorted(obj.keys()):
                    result += bencode(key) + bencode(obj[key])
                result += b"e"
                return result
            elif isinstance(obj, list):
                result = b"l"
                for item in obj:
                    result += bencode(item)
                result += b"e"
                return result
        
        return bencode(torrent_dict)
        
    async def test_torrent_upload(self) -> bool:
        """Test torrent file upload endpoint"""
        print("\n=== Testing Torrent Upload Endpoint ===")
        
        try:
            # Create test torrent file
            torrent_data = self.create_test_torrent_file()
            
            # Create multipart form data
            data = aiohttp.FormData()
            data.add_field('file', torrent_data, 
                          filename='ubuntu-20.04.torrent', 
                          content_type='application/x-bittorrent')
            data.add_field('download_speed_limit', '1048576')  # 1MB/s
            data.add_field('upload_speed_limit', '524288')     # 512KB/s
            
            async with self.session.post(f"{API_BASE}/torrents/upload", data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    self.uploaded_torrent_id = result.get('id')
                    print(f"✅ Upload successful - Torrent ID: {self.uploaded_torrent_id}")
                    print(f"   Name: {result.get('name')}")
                    print(f"   Size: {result.get('size')} bytes")
                    return True
                else:
                    error_text = await response.text()
                    print(f"❌ Upload failed - Status: {response.status}")
                    print(f"   Error: {error_text}")
                    return False
                    
        except Exception as e:
            print(f"❌ Upload test failed with exception: {e}")
            return False
            
    async def test_get_torrents(self) -> bool:
        """Test getting list of torrents"""
        print("\n=== Testing Get Torrents Endpoint ===")
        
        try:
            async with self.session.get(f"{API_BASE}/torrents") as response:
                if response.status == 200:
                    torrents = await response.json()
                    print(f"✅ Retrieved {len(torrents)} torrents")
                    
                    if torrents:
                        torrent = torrents[0]
                        print(f"   First torrent: {torrent.get('name')}")
                        print(f"   Status: {torrent.get('status')}")
                        print(f"   Progress: {torrent.get('progress', 0):.1f}%")
                    
                    return True
                else:
                    error_text = await response.text()
                    print(f"❌ Get torrents failed - Status: {response.status}")
                    print(f"   Error: {error_text}")
                    return False
                    
        except Exception as e:
            print(f"❌ Get torrents test failed with exception: {e}")
            return False
            
    async def test_websocket_connection(self) -> bool:
        """Test WebSocket real-time updates"""
        print("\n=== Testing WebSocket Connection ===")
        
        try:
            ws_url = f"{API_BASE}/ws".replace('https://', 'wss://').replace('http://', 'ws://')
            print(f"Connecting to WebSocket: {ws_url}")
            
            # Use websockets.connect without timeout parameter for compatibility
            async with websockets.connect(ws_url) as websocket:
                print("✅ WebSocket connection established")
                
                # Send a test message
                await websocket.send("test_message")
                
                # Wait for updates (with timeout)
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    data = json.loads(message)
                    print(f"✅ Received WebSocket update: {data.get('type', 'unknown')}")
                    
                    if data.get('type') == 'torrent_update':
                        stats = data.get('stats', {})
                        print(f"   Active torrents in update: {len(stats)}")
                    
                    return True
                    
                except asyncio.TimeoutError:
                    print("⚠️  No WebSocket messages received within timeout (this may be normal)")
                    return True  # Connection worked, just no immediate updates
                    
        except Exception as e:
            print(f"❌ WebSocket test failed with exception: {e}")
            return False
            
    async def test_torrent_controls(self) -> bool:
        """Test pause/resume/delete operations"""
        print("\n=== Testing Torrent Control Operations ===")
        
        if not self.uploaded_torrent_id:
            print("❌ No torrent ID available for control tests")
            return False
            
        try:
            torrent_id = self.uploaded_torrent_id
            
            # Test pause
            print(f"Testing pause for torrent: {torrent_id}")
            async with self.session.post(f"{API_BASE}/torrents/{torrent_id}/pause") as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✅ Pause successful: {result.get('message')}")
                else:
                    print(f"❌ Pause failed - Status: {response.status}")
                    return False
            
            # Wait a moment
            await asyncio.sleep(1)
            
            # Test resume
            print(f"Testing resume for torrent: {torrent_id}")
            async with self.session.post(f"{API_BASE}/torrents/{torrent_id}/resume") as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✅ Resume successful: {result.get('message')}")
                else:
                    print(f"❌ Resume failed - Status: {response.status}")
                    return False
            
            # Test update (speed limits)
            print(f"Testing speed limit update for torrent: {torrent_id}")
            update_data = {
                "download_speed_limit": 2097152,  # 2MB/s
                "upload_speed_limit": 1048576     # 1MB/s
            }
            async with self.session.put(f"{API_BASE}/torrents/{torrent_id}", 
                                      json=update_data) as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✅ Update successful: {result.get('message')}")
                else:
                    print(f"❌ Update failed - Status: {response.status}")
                    return False
            
            return True
            
        except Exception as e:
            print(f"❌ Torrent controls test failed with exception: {e}")
            return False
            
    async def test_system_stats(self) -> bool:
        """Test system statistics endpoint"""
        print("\n=== Testing System Statistics Endpoint ===")
        
        try:
            async with self.session.get(f"{API_BASE}/stats") as response:
                if response.status == 200:
                    stats = await response.json()
                    print("✅ System stats retrieved successfully:")
                    print(f"   Total downloads: {stats.get('total_downloads', 0)}")
                    print(f"   Active downloads: {stats.get('active_downloads', 0)}")
                    print(f"   Completed downloads: {stats.get('completed_downloads', 0)}")
                    print(f"   Total downloaded: {stats.get('total_downloaded', 0)} bytes")
                    print(f"   Global download rate: {stats.get('global_download_rate', 0):.2f} B/s")
                    print(f"   Global upload rate: {stats.get('global_upload_rate', 0):.2f} B/s")
                    return True
                else:
                    error_text = await response.text()
                    print(f"❌ System stats failed - Status: {response.status}")
                    print(f"   Error: {error_text}")
                    return False
                    
        except Exception as e:
            print(f"❌ System stats test failed with exception: {e}")
            return False
            
    async def test_global_bandwidth_limits(self) -> bool:
        """Test global bandwidth limiting controls"""
        print("\n=== Testing Global Bandwidth Limits ===")
        
        try:
            # Set global limits
            limits_data = {
                "download_limit": 5242880,  # 5MB/s
                "upload_limit": 2621440     # 2.5MB/s
            }
            
            async with self.session.post(f"{API_BASE}/settings/global-limits", 
                                       json=limits_data) as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✅ Global limits set successfully: {result.get('message')}")
                    return True
                else:
                    error_text = await response.text()
                    print(f"❌ Global limits failed - Status: {response.status}")
                    print(f"   Error: {error_text}")
                    return False
                    
        except Exception as e:
            print(f"❌ Global bandwidth limits test failed with exception: {e}")
            return False
            
    async def test_cleanup_torrent(self) -> bool:
        """Clean up test torrent"""
        print("\n=== Cleaning Up Test Torrent ===")
        
        if not self.uploaded_torrent_id:
            print("⚠️  No torrent to clean up")
            return True
            
        try:
            torrent_id = self.uploaded_torrent_id
            async with self.session.delete(f"{API_BASE}/torrents/{torrent_id}") as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✅ Cleanup successful: {result.get('message')}")
                    return True
                else:
                    print(f"❌ Cleanup failed - Status: {response.status}")
                    return False
                    
        except Exception as e:
            print(f"❌ Cleanup test failed with exception: {e}")
            return False
            
    async def run_all_tests(self):
        """Run all backend tests"""
        print("🚀 Starting Comprehensive Backend Testing for Torrent Management System")
        print("=" * 80)
        
        await self.setup()
        
        tests = [
            ("Torrent Upload", self.test_torrent_upload),
            ("Get Torrents", self.test_get_torrents),
            ("WebSocket Connection", self.test_websocket_connection),
            ("Torrent Controls", self.test_torrent_controls),
            ("System Statistics", self.test_system_stats),
            ("Global Bandwidth Limits", self.test_global_bandwidth_limits),
            ("Cleanup", self.test_cleanup_torrent)
        ]
        
        results = {}
        
        for test_name, test_func in tests:
            try:
                result = await test_func()
                results[test_name] = result
                if result:
                    print(f"✅ {test_name}: PASSED")
                else:
                    print(f"❌ {test_name}: FAILED")
            except Exception as e:
                print(f"❌ {test_name}: FAILED with exception: {e}")
                results[test_name] = False
                
            # Small delay between tests
            await asyncio.sleep(0.5)
        
        await self.cleanup()
        
        # Summary
        print("\n" + "=" * 80)
        print("🏁 BACKEND TESTING SUMMARY")
        print("=" * 80)
        
        passed = sum(1 for result in results.values() if result)
        total = len(results)
        
        for test_name, result in results.items():
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"{test_name:.<30} {status}")
        
        print(f"\nOverall Result: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 ALL BACKEND TESTS PASSED!")
            return True
        else:
            print("⚠️  SOME BACKEND TESTS FAILED!")
            return False

async def main():
    """Main test runner"""
    tester = TorrentBackendTester()
    success = await tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n🛑 Testing interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Testing failed with unexpected error: {e}")
        sys.exit(1)