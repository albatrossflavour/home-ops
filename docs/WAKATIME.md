# Wakatime Integration for Home-Ops

This project includes comprehensive Wakatime integration to track time spent on homelab development and operations.

## Current Integration

### Project Tracking

The project is configured to track time with the project name "home-ops":

- Badge: [![wakatime](https://wakatime.com/badge/user/97c75e0e-3119-41db-b612-8c629b4e97f4/project/ef519725-9fe1-48f5-83e1-57bf5545021e.svg)](https://wakatime.com/badge/user/97c75e0e-3119-41db-b612-8c629b4e97f4/project/ef519725-9fe1-48f5-83e1-57bf5545021e)
- Project file: `.wakatime-project` ensures consistent project naming
- VS Code settings include `wakatime.project_name` and `wakatime.include_only_with_project_file`

### File Type Tracking

The integration tracks time across various file types used in this homelab:

```json
{
  "*.yaml": "yaml",
  "*.yml": "yaml",
  "*.j2": "jinja",
  "Taskfile.yaml": "yaml",
  "kustomization.yaml": "yaml",
  "*.sops.yaml": "yaml",
  "*.sops.yml": "yaml"
}
```

### Activity Categories

Time tracking covers these main activity areas:

#### Infrastructure as Code

- **Kubernetes manifests**: YAML files for deployments, services, ingress
- **Flux configurations**: GitOps setup and kustomizations
- **Helm charts**: Application deployments and values files
- **Talos configurations**: Node and cluster setup

#### Templating and Configuration

- **Jinja2 templates**: Bootstrap template customization
- **SOPS encrypted secrets**: Secure configuration management
- **Config files**: Main configuration and environment setup

#### Documentation and Scripts

- **Markdown files**: Documentation, guides, and procedures
- **Shell scripts**: Automation and utility scripts
- **Task definitions**: Taskfile.yaml workflows
- **Python scripts**: Bootstrap and validation scripts

#### GitOps and CI/CD

- **GitHub Actions**: Workflow definitions
- **Renovate configs**: Dependency management
- **Git operations**: Repository management

## Tracked Metrics

### Development Time

Track time spent on:

- Application deployment and configuration
- Infrastructure updates and maintenance
- Troubleshooting and debugging
- Documentation writing
- Template customization

### Operational Time

Monitor time for:

- Cluster maintenance
- Application updates
- Security patches
- Monitoring setup
- Backup configuration

### Learning and Research

Capture time for:

- Technology research
- Best practice implementation
- Community engagement
- Documentation review

## Setup Instructions

### 1. Install Wakatime Extension

For VS Code:

```bash
# The extension is already recommended in .vscode/extensions.json
# Install via Command Palette: Extensions: Install Recommended Extensions
```

For other editors, visit: https://wakatime.com/plugins

### 2. Configure Wakatime

1. Sign up at [wakatime.com](https://wakatime.com)
2. Get your API key from [wakatime.com/api-key](https://wakatime.com/api-key)
3. Configure the extension with your API key
4. The project will automatically be tracked as "home-ops"

### 3. Verify Tracking

```bash
# Check that .wakatime-project exists
cat .wakatime-project

# Verify VS Code settings
cat .vscode/settings.json | grep wakatime
```

## Advanced Configuration

### Custom Categories

You can create custom categories in Wakatime dashboard:

- **Infrastructure**: Kubernetes, Talos, networking
- **Applications**: Media stack, monitoring, home automation  
- **Security**: SOPS, certificates, authentication
- **Documentation**: README files, guides, procedures
- **Automation**: Scripts, workflows, CI/CD

### Time Goals

Set weekly/monthly goals for:

- Infrastructure development: 5-10 hours/week
- Application management: 2-5 hours/week
- Documentation: 1-2 hours/week
- Learning: 2-3 hours/week

### Productivity Insights

Use Wakatime data to:

- Identify peak productivity hours
- Track time spent on different technologies
- Monitor project progress over time
- Plan maintenance windows
- Balance development vs operational tasks

## Integration with Other Tools

### GitHub Integration

Link commits to time tracking:

```bash
# Wakatime can correlate commits with tracked time
# Useful for understanding development velocity
```

### Project Management

Export Wakatime data for:

- Sprint planning
- Effort estimation
- Resource allocation
- Progress reporting

## Privacy and Data

### What's Tracked

- File names and types
- Time spent in editor
- Programming languages used
- Project names

### What's NOT Tracked

- File contents
- Keystrokes
- Secret data
- Personal information

### Data Export

Export your data anytime:

- Dashboard: wakatime.com/dashboard
- API: wakatime.com/developers
- Reports: Weekly/monthly summaries

## Troubleshooting

### Common Issues

**Project not being tracked:**

```bash
# Ensure .wakatime-project file exists
echo "home-ops" > .wakatime-project

# Check VS Code settings
grep wakatime .vscode/settings.json
```

**Time not being recorded:**

- Verify Wakatime extension is installed and active
- Check API key configuration
- Ensure heartbeats are being sent (check extension logs)

**Incorrect project name:**

- Verify `.wakatime-project` contains "home-ops"
- Check `wakatime.project_name` in VS Code settings
- Restart editor after configuration changes

### Debug Commands

```bash
# Check Wakatime plugin status
wakatime --version

# Verify API key (if CLI installed)
wakatime --config-read api_key

# Test heartbeat
wakatime --write --file README.md --project home-ops
```

## Reporting and Analytics

### Dashboard Views

Access your stats at:

- Overview: https://wakatime.com/dashboard
- Projects: https://wakatime.com/projects
- Languages: https://wakatime.com/languages

### Custom Reports

Create reports for:

- Monthly homelab development time
- Technology focus areas (Kubernetes vs applications)
- Seasonal patterns (more time in winter?)
- Goal tracking and progress

### Sharing Stats

Embed badges in documentation:

```markdown
[![wakatime](https://wakatime.com/badge/user/YOUR-USER-ID/project/YOUR-PROJECT-ID.svg)](https://wakatime.com/badge/user/YOUR-USER-ID/project/YOUR-PROJECT-ID)
```

This integration provides valuable insights into your homelab development patterns and helps optimize your productivity!
