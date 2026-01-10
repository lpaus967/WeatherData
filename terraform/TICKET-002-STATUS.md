# TICKET-002: EC2 Instance Provisioning - STATUS

**Status**: 📝 Ready for Launch (Guides Complete, Awaiting User Action)
**Date**: 2026-01-10

## What's Complete

### ✅ Documentation Created

1. **EC2-QUICK-REFERENCE.md**
   - Copy-paste ready configuration values
   - Quick verification commands
   - Docker test commands
   - Cost estimates

2. **TICKET-002-EC2-LAUNCH-GUIDE.md**
   - Complete 9-step launch process
   - IAM role creation instructions
   - Bootstrap script (user data) for automatic setup
   - Post-launch verification checklist
   - Troubleshooting section
   - Cost breakdown

### ✅ Bootstrap Script Features

The user data script automatically installs:
- Docker CE (latest)
- AWS CLI v2
- Python 3 + pip
- CloudWatch Agent
- System updates
- Directory structure for weather pipeline
- CloudWatch configuration for monitoring

**Estimated Setup Time**: ~5 minutes (automatic after launch)

## What You Need to Do

### Step 1: Launch EC2 Instance

Follow the guide at `TICKET-002-EC2-LAUNCH-GUIDE.md`:

1. Go to AWS Console → EC2 → Launch Instance
2. Configure instance:
   - **Name**: weather-pipeline-processor
   - **AMI**: Ubuntu Server 22.04 LTS (64-bit x86)
   - **Instance Type**: t3.small
   - **Key Pair**: Proceed without key pair (use SSM)
   - **Storage**: 50 GB gp3, encrypted
   - **IAM Role**: Create new role `EC2-WeatherPipeline-Role` with:
     - AmazonS3FullAccess
     - CloudWatchAgentServerPolicy
     - AmazonSSMManagedInstanceCore
   - **User Data**: Copy from guide (lines 145-312)

3. Click **Launch Instance**

### Step 2: Wait for Setup (5-10 minutes)

The instance will:
1. Launch and pass status checks (~2 min)
2. Run user data script (~3 min)
3. Reboot automatically (~2 min)
4. Be ready for use

### Step 3: Connect and Verify

Use AWS Systems Manager Session Manager:
1. EC2 Console → Select instance → Click **Connect**
2. Choose **Session Manager** tab
3. Click **Connect**

Run verification commands from `EC2-QUICK-REFERENCE.md`:
```bash
# Check setup status
cat /home/ubuntu/weather-pipeline/setup-status.txt

# Verify Docker
docker --version

# Test S3 access
aws s3 ls s3://sat-data-automation-test/

# Check CloudWatch Agent
sudo systemctl status amazon-cloudwatch-agent
```

### Step 4: Build Docker Image

```bash
# Clone or copy your repository
cd /home/ubuntu/weather-pipeline

# Option A: Clone from GitHub
git clone https://github.com/yourusername/WeatherData.git .

# Option B: Copy from local machine (from your laptop)
# scp -r ~/Documents/GIT/WeatherData/* ubuntu@<PUBLIC-IP>:/home/ubuntu/weather-pipeline/

# Build Docker image
cd docker
docker build -t weather-processor:latest .

# Test Docker image
docker run --rm weather-processor:latest python3 -c "from herbie import Herbie; print('Herbie OK')"
```

## Cost Estimate

### Monthly Costs (Spot Instance - Recommended)

| Item | Cost |
|------|------|
| EC2 t3.small (Spot 24/7) | $4.56 |
| EBS gp3 (50 GB) | $4.00 |
| Data Transfer (50 GB/mo) | $4.50 |
| CloudWatch Logs (5 GB/mo) | $2.50 |
| **Subtotal** | **$15.56/mo** |
| S3 (from TICKET-001) | $3.40 |
| **Total Pipeline** | **$18.96/mo** |

**On-Demand Alternative**: $29.58/mo (+$10.62/mo)

## Verification Checklist

Before marking TICKET-002 complete:

- [ ] EC2 instance is running
- [ ] Instance passed 2/2 status checks
- [ ] Can connect via Systems Manager Session Manager
- [ ] Docker installed and working (`docker --version`)
- [ ] AWS CLI installed (`aws --version`)
- [ ] S3 access verified (`aws s3 ls s3://sat-data-automation-test/`)
- [ ] Python 3 installed (`python3 --version`)
- [ ] CloudWatch Agent running (`sudo systemctl status amazon-cloudwatch-agent`)
- [ ] Repository cloned/copied to instance
- [ ] Docker image built (`docker images | grep weather-processor`)
- [ ] Docker image tested successfully (Herbie import works)
- [ ] No errors in user data log (`cat /var/log/user-data.log | tail -50`)

## Quick Reference

**Instance Name**: weather-pipeline-processor
**Instance Type**: t3.small
**Region**: us-east-2
**S3 Bucket**: sat-data-automation-test
**IAM Role**: EC2-WeatherPipeline-Role
**Docker Image**: weather-processor:latest

## After TICKET-002 Complete

Once all verification items are checked:

1. Create `TICKET-002-COMPLETE.md` documentation
2. Update `TICKETS.md` to mark TICKET-002 as complete
3. Proceed to TICKET-004: Create HRRR download script with Herbie

## Current Pipeline Status

- ✅ **TICKET-001**: S3 Infrastructure - Complete
- 📝 **TICKET-002**: EC2 Instance - Ready to Launch (You are here)
- ✅ **TICKET-003**: Docker Container - Complete
- 📝 **TICKET-004**: Download Script - Pending (next)
- 📝 **TICKET-005**: Variable Config - Pending
- 📝 **TICKET-006**: Processing Script - Pending

---

**Next Action**: Launch EC2 instance following `TICKET-002-EC2-LAUNCH-GUIDE.md`

**Estimated Time to Complete**: 30-45 minutes (including AWS Console setup and verification)
