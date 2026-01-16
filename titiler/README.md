# TiTiler Dynamic Tile Server

TiTiler is deployed as a parallel tile serving system alongside the existing pre-generated tile approach. This allows testing dynamic tile generation without disrupting current production workflows.

## Quick Start

### 1. Setup Environment

```bash
cd titiler

# Copy example environment file
cp .env.example .env

# Edit .env with your AWS credentials
# Required: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
```

### 2. Start TiTiler

```bash
docker-compose up -d
```

### 3. Verify Health

```bash
curl http://localhost:8000/healthz
```

## API Endpoints

TiTiler provides standard endpoints for working with Cloud Optimized GeoTIFFs (COGs).

### Tile Endpoint

Fetch a tile at specific zoom/x/y coordinates:

```
GET /cog/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.{format}?url={cog_url}
```

**Parameters:**
- `z`: Zoom level
- `x`: Tile column
- `y`: Tile row
- `format`: Output format (png, jpg, webp)
- `url`: URL to the COG file (S3 or HTTP)

**Example:**
```bash
curl "http://localhost:8000/cog/tiles/WebMercatorQuad/4/3/6@1x.png?url=s3://sat-data-automation-test/processed-cogs/2026/01/10/temperature_2m_hrrr.20260110.t22z.f00.tif" --output tile.png
```

### TileJSON Endpoint

Get tile URL template and metadata:

```
GET /cog/WebMercatorQuad/tilejson.json?url={cog_url}
```

**Example:**
```bash
curl "http://localhost:8000/cog/WebMercatorQuad/tilejson.json?url=s3://sat-data-automation-test/processed-cogs/2026/01/10/temperature_2m_hrrr.20260110.t22z.f00.tif"
```

### COG Info

Get metadata about a COG:

```
GET /cog/info?url={cog_url}
```

**Example:**
```bash
curl "http://localhost:8000/cog/info?url=s3://sat-data-automation-test/processed-cogs/2026/01/10/temperature_2m_hrrr.20260110.t22z.f00.tif"
```

**Response includes:**
- Bounds (geographic extent)
- CRS (coordinate reference system)
- Band information
- Data type
- Overviews

### COG Statistics

Get band statistics:

```
GET /cog/statistics?url={cog_url}
```

**Example:**
```bash
curl "http://localhost:8000/cog/statistics?url=s3://sat-data-automation-test/processed-cogs/2026/01/10/temperature_2m_hrrr.20260110.t22z.f00.tif"
```

### Preview Image

Generate a preview image of the entire COG:

```
GET /cog/preview?url={cog_url}
```

**Optional parameters:**
- `max_size`: Maximum dimension (default: 1024)
- `width`/`height`: Specific dimensions

**Example:**
```bash
curl "http://localhost:8000/cog/preview?url=s3://sat-data-automation-test/processed-cogs/2026/01/10/temperature_2m_hrrr.20260110.t22z.f00.tif&max_size=512" --output preview.png
```

### Point Query

Get the value at a specific coordinate:

```
GET /cog/point/{lon},{lat}?url={cog_url}
```

**Example:**
```bash
curl "http://localhost:8000/cog/point/-83.0,40.0?url=s3://sat-data-automation-test/processed-cogs/2026/01/10/temperature_2m_hrrr.20260110.t22z.f00.tif"
```

### Health Check

```
GET /healthz
```

## S3 COG Path Structure

Our S3 bucket structure:

```
s3://sat-data-automation-test/processed-cogs/YYYY/MM/DD/{variable}_hrrr.YYYYMMDD.tHHz.fFF.tif
```

**Variables available:**
- `temperature_2m` - 2m temperature
- `dewpoint_2m` - 2m dewpoint
- `relative_humidity_2m` - 2m relative humidity
- `wind_speed_10m` - 10m wind speed
- `wind_gust_10m` - Wind gust
- `wind_direction_10m` - Wind direction
- `total_cloud_cover` - Total cloud cover
- `low_cloud_cover` - Low cloud cover
- `visibility` - Visibility
- `precipitation_rate` - Precipitation rate
- And more...

**Example URLs:**
```
s3://sat-data-automation-test/processed-cogs/2026/01/10/temperature_2m_hrrr.20260110.t00z.f00.tif
s3://sat-data-automation-test/processed-cogs/2026/01/10/wind_speed_10m_hrrr.20260110.t06z.f03.tif
```

## Testing

Run the test suite to validate TiTiler is working correctly:

```bash
python ../scripts/titiler/test_titiler.py
python ../scripts/titiler/test_titiler.py --verbose
```

Generate sample URLs for testing:

```bash
python ../scripts/titiler/generate_sample_urls.py
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_ACCESS_KEY_ID` | - | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | - | AWS secret key |
| `AWS_REGION` | `us-east-2` | AWS region |
| `TITILER_API_CORS_ORIGINS` | `*` | Allowed CORS origins |
| `GDAL_CACHEMAX` | `200` | GDAL cache size (MB) |
| `VSI_CACHE_SIZE` | `5000000` | VSI cache size (bytes) |

### Docker Compose Commands

```bash
# Start in foreground (see logs)
docker-compose up

# Start in background
docker-compose up -d

# View logs
docker-compose logs -f titiler

# Stop
docker-compose down

# Restart
docker-compose restart

# Rebuild (if using custom Dockerfile)
docker-compose up --build
```

## Using with Leaflet/MapLibre

TileJSON provides the tile URL template for map libraries:

```javascript
// Fetch TileJSON
const tileJsonUrl = `http://localhost:8000/cog/WebMercatorQuad/tilejson.json?url=${encodeURIComponent(cogUrl)}`;
const tileJson = await fetch(tileJsonUrl).then(r => r.json());

// Use tiles array in your map library
// tileJson.tiles[0] contains the tile URL template
```

## Comparison with Pre-Generated Tiles

| Aspect | Pre-Generated | TiTiler Dynamic |
|--------|---------------|-----------------|
| Latency | Very low (S3 direct) | Higher (on-demand render) |
| Storage | High (all zoom levels) | Low (COG only) |
| Flexibility | Fixed zoom/style | Any zoom/style |
| Updates | Regenerate tiles | Instant (serve new COG) |

## Troubleshooting

### Common Issues

**1. "Access Denied" errors**
- Verify AWS credentials in `.env`
- Check S3 bucket permissions
- Ensure COG files are accessible

**2. Slow tile generation**
- Verify COGs have overviews (`gdalinfo file.tif | grep "Overviews"`)
- Increase `GDAL_CACHEMAX` for larger files
- Check network connectivity to S3

**3. CORS errors in browser**
- Set `TITILER_API_CORS_ORIGINS` to your frontend domain
- For development, use `*` to allow all origins

**4. Container not starting**
- Check Docker daemon is running
- Verify port 8000 is not in use
- Check logs: `docker-compose logs titiler`

**5. "Not Found" for tile requests**
- Ensure URL includes `WebMercatorQuad` in path
- Correct format: `/cog/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png?url=...`

## Future: Production Deployment

For production, TiTiler will be deployed to ECS Fargate with:
- HTTPS via Application Load Balancer
- CloudFront CDN for caching
- Auto-scaling based on demand
- Terraform configuration in `/terraform/titiler/`
