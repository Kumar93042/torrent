import React, { useState, useEffect, useCallback } from "react";
import "./App.css";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

function App() {
  const [torrents, setTorrents] = useState([]);
  const [systemStats, setSystemStats] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [socket, setSocket] = useState(null);
  const [globalLimits, setGlobalLimits] = useState({ download: '', upload: '' });
  const [showSettings, setShowSettings] = useState(false);

  // Initialize WebSocket connection
  useEffect(() => {
    const wsUrl = BACKEND_URL.replace('https://', 'wss://').replace('http://', 'ws://');
    const ws = new WebSocket(`${wsUrl}/api/ws`);
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'torrent_update') {
        setTorrents(prev => prev.map(torrent => {
          const stats = data.stats[torrent.id];
          if (stats) {
            return {
              ...torrent,
              progress: stats.progress,
              download_rate: stats.download_rate,
              upload_rate: stats.upload_rate,
              eta: stats.eta
            };
          }
          return torrent;
        }));
      }
    };
    
    setSocket(ws);
    
    return () => {
      ws.close();
    };
  }, []);

  // Load torrents and stats
  const loadData = useCallback(async () => {
    try {
      const [torrentsRes, statsRes] = await Promise.all([
        axios.get(`${API}/torrents`),
        axios.get(`${API}/stats`)
      ]);
      setTorrents(torrentsRes.data);
      setSystemStats(statsRes.data);
    } catch (error) {
      console.error('Error loading data:', error);
    }
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, [loadData]);

  // File upload handling
  const handleFileUpload = async (file) => {
    if (!file.name.endsWith('.torrent')) {
      alert('Please upload a .torrent file');
      return;
    }

    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      await axios.post(`${API}/torrents/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      loadData();
    } catch (error) {
      console.error('Error uploading torrent:', error);
      alert('Error uploading torrent file');
    } finally {
      setUploading(false);
    }
  };

  // Drag and drop handlers
  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      handleFileUpload(files[0]);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setDragOver(false);
  };

  // Torrent control functions
  const pauseTorrent = async (torrentId) => {
    try {
      await axios.post(`${API}/torrents/${torrentId}/pause`);
      loadData();
    } catch (error) {
      console.error('Error pausing torrent:', error);
    }
  };

  const resumeTorrent = async (torrentId) => {
    try {
      await axios.post(`${API}/torrents/${torrentId}/resume`);
      loadData();
    } catch (error) {
      console.error('Error resuming torrent:', error);
    }
  };

  const deleteTorrent = async (torrentId) => {
    if (window.confirm('Are you sure you want to delete this torrent?')) {
      try {
        await axios.delete(`${API}/torrents/${torrentId}`);
        loadData();
      } catch (error) {
        console.error('Error deleting torrent:', error);
      }
    }
  };

  const updateTorrentLimits = async (torrentId, downloadLimit, uploadLimit) => {
    try {
      await axios.put(`${API}/torrents/${torrentId}`, {
        download_speed_limit: downloadLimit || null,
        upload_speed_limit: uploadLimit || null
      });
      loadData();
    } catch (error) {
      console.error('Error updating torrent limits:', error);
    }
  };

  const setGlobalLimitsApi = async () => {
    try {
      await axios.post(`${API}/settings/global-limits`, {
        download_limit: globalLimits.download ? parseInt(globalLimits.download) * 1024 : null,
        upload_limit: globalLimits.upload ? parseInt(globalLimits.upload) * 1024 : null
      });
      alert('Global limits updated');
    } catch (error) {
      console.error('Error setting global limits:', error);
    }
  };

  // Format bytes
  const formatBytes = (bytes) => {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const formatSpeed = (bytesPerSec) => {
    return formatBytes(bytesPerSec) + '/s';
  };

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      {/* Header */}
      <header className="bg-gray-800 shadow-lg">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-4">
            <div className="flex items-center space-x-4">
              <h1 className="text-2xl font-bold text-blue-400">⚡ TorrentManager Pro</h1>
              {systemStats && (
                <div className="hidden md:flex space-x-4 text-sm">
                  <span className="text-green-400">↓ {formatSpeed(systemStats.global_download_rate)}</span>
                  <span className="text-red-400">↑ {formatSpeed(systemStats.global_upload_rate)}</span>
                  <span className="text-blue-400">{systemStats.active_downloads} active</span>
                </div>
              )}
            </div>
            <button
              onClick={() => setShowSettings(!showSettings)}
              className="p-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
            >
              ⚙️
            </button>
          </div>
        </div>
      </header>

      {/* Settings Panel */}
      {showSettings && (
        <div className="bg-gray-800 border-b border-gray-700">
          <div className="max-w-7xl mx-auto px-4 py-4">
            <div className="flex items-center space-x-4">
              <h3 className="font-semibold">Global Speed Limits:</h3>
              <input
                type="number"
                placeholder="Download (KB/s)"
                value={globalLimits.download}
                onChange={(e) => setGlobalLimits(prev => ({ ...prev, download: e.target.value }))}
                className="px-3 py-1 bg-gray-700 border border-gray-600 rounded"
              />
              <input
                type="number"
                placeholder="Upload (KB/s)"
                value={globalLimits.upload}
                onChange={(e) => setGlobalLimits(prev => ({ ...prev, upload: e.target.value }))}
                className="px-3 py-1 bg-gray-700 border border-gray-600 rounded"
              />
              <button
                onClick={setGlobalLimitsApi}
                className="px-4 py-1 bg-green-600 hover:bg-green-700 rounded transition-colors"
              >
                Apply
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Upload Area */}
        <div
          className={`mb-8 p-8 border-2 border-dashed rounded-xl transition-all ${
            dragOver
              ? 'border-blue-400 bg-blue-900/20'
              : 'border-gray-600 hover:border-gray-500'
          }`}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
        >
          <div className="text-center">
            <div className="text-4xl mb-4">📁</div>
            <p className="text-lg mb-4">
              {uploading ? 'Uploading...' : 'Drop .torrent files here or click to browse'}
            </p>
            <input
              type="file"
              accept=".torrent"
              onChange={(e) => e.target.files[0] && handleFileUpload(e.target.files[0])}
              className="hidden"
              id="file-input"
            />
            <label
              htmlFor="file-input"
              className="cursor-pointer px-6 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors inline-block"
            >
              Browse Files
            </label>
          </div>
        </div>

        {/* System Stats */}
        {systemStats && (
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
            <div className="bg-gray-800 p-4 rounded-lg">
              <div className="text-2xl font-bold text-blue-400">{systemStats.total_downloads}</div>
              <div className="text-sm text-gray-400">Total Downloads</div>
            </div>
            <div className="bg-gray-800 p-4 rounded-lg">
              <div className="text-2xl font-bold text-green-400">{systemStats.active_downloads}</div>
              <div className="text-sm text-gray-400">Active</div>
            </div>
            <div className="bg-gray-800 p-4 rounded-lg">
              <div className="text-2xl font-bold text-purple-400">{systemStats.completed_downloads}</div>
              <div className="text-sm text-gray-400">Completed</div>
            </div>
            <div className="bg-gray-800 p-4 rounded-lg">
              <div className="text-2xl font-bold text-yellow-400">{formatBytes(systemStats.total_downloaded)}</div>
              <div className="text-sm text-gray-400">Total Size</div>
            </div>
          </div>
        )}

        {/* Torrents List */}
        <div className="space-y-4">
          {torrents.length === 0 ? (
            <div className="text-center py-12 text-gray-400">
              <div className="text-4xl mb-4">🌟</div>
              <p>No torrents yet. Upload your first .torrent file to get started!</p>
            </div>
          ) : (
            torrents.map((torrent) => (
              <TorrentCard
                key={torrent.id}
                torrent={torrent}
                onPause={() => pauseTorrent(torrent.id)}
                onResume={() => resumeTorrent(torrent.id)}
                onDelete={() => deleteTorrent(torrent.id)}
                onUpdateLimits={(downloadLimit, uploadLimit) =>
                  updateTorrentLimits(torrent.id, downloadLimit, uploadLimit)
                }
                formatBytes={formatBytes}
                formatSpeed={formatSpeed}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

// Torrent Card Component
function TorrentCard({ torrent, onPause, onResume, onDelete, onUpdateLimits, formatBytes, formatSpeed }) {
  const [showLimits, setShowLimits] = useState(false);
  const [limits, setLimits] = useState({ download: '', upload: '' });

  const getStatusColor = (status) => {
    switch (status) {
      case 'downloading': return 'text-green-400';
      case 'completed': return 'text-blue-400';
      case 'paused': return 'text-yellow-400';
      case 'error': return 'text-red-400';
      default: return 'text-gray-400';
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'downloading': return '⬇️';
      case 'completed': return '✅';
      case 'paused': return '⏸️';
      case 'error': return '❌';
      default: return '⏳';
    }
  };

  return (
    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
      <div className="flex items-start justify-between mb-4">
        <div className="flex-1">
          <h3 className="font-semibold text-lg text-white mb-2">{torrent.name}</h3>
          <div className="flex items-center space-x-4 text-sm">
            <span className={`flex items-center space-x-1 ${getStatusColor(torrent.status)}`}>
              <span>{getStatusIcon(torrent.status)}</span>
              <span className="capitalize">{torrent.status}</span>
            </span>
            <span className="text-gray-400">{formatBytes(torrent.size)}</span>
            {torrent.eta && torrent.eta !== 'Unknown' && (
              <span className="text-blue-400">ETA: {torrent.eta}</span>
            )}
          </div>
        </div>
        <div className="flex space-x-2">
          {torrent.status === 'downloading' ? (
            <button
              onClick={onPause}
              className="p-2 bg-yellow-600 hover:bg-yellow-700 rounded transition-colors"
              title="Pause"
            >
              ⏸️
            </button>
          ) : torrent.status === 'paused' ? (
            <button
              onClick={onResume}
              className="p-2 bg-green-600 hover:bg-green-700 rounded transition-colors"
              title="Resume"
            >
              ▶️
            </button>
          ) : null}
          <button
            onClick={() => setShowLimits(!showLimits)}
            className="p-2 bg-blue-600 hover:bg-blue-700 rounded transition-colors"
            title="Settings"
          >
            ⚙️
          </button>
          <button
            onClick={onDelete}
            className="p-2 bg-red-600 hover:bg-red-700 rounded transition-colors"
            title="Delete"
          >
            🗑️
          </button>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="mb-4">
        <div className="flex justify-between text-sm mb-1">
          <span>{torrent.progress?.toFixed(1)}%</span>
          <div className="flex space-x-4">
            <span className="text-green-400">↓ {formatSpeed(torrent.download_rate || 0)}</span>
            <span className="text-red-400">↑ {formatSpeed(torrent.upload_rate || 0)}</span>
          </div>
        </div>
        <div className="w-full bg-gray-700 rounded-full h-2">
          <div
            className="bg-gradient-to-r from-blue-500 to-green-500 h-2 rounded-full transition-all duration-300"
            style={{ width: `${Math.min(torrent.progress || 0, 100)}%` }}
          />
        </div>
      </div>

      {/* Speed Limits Settings */}
      {showLimits && (
        <div className="bg-gray-700 p-4 rounded-lg">
          <div className="flex items-center space-x-4 mb-2">
            <input
              type="number"
              placeholder="Download limit (KB/s)"
              value={limits.download}
              onChange={(e) => setLimits(prev => ({ ...prev, download: e.target.value }))}
              className="px-3 py-1 bg-gray-600 border border-gray-500 rounded text-sm"
            />
            <input
              type="number"
              placeholder="Upload limit (KB/s)"
              value={limits.upload}
              onChange={(e) => setLimits(prev => ({ ...prev, upload: e.target.value }))}
              className="px-3 py-1 bg-gray-600 border border-gray-500 rounded text-sm"
            />
            <button
              onClick={() => {
                onUpdateLimits(
                  limits.download ? parseInt(limits.download) * 1024 : null,
                  limits.upload ? parseInt(limits.upload) * 1024 : null
                );
                setLimits({ download: '', upload: '' });
              }}
              className="px-4 py-1 bg-green-600 hover:bg-green-700 rounded text-sm transition-colors"
            >
              Apply
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;