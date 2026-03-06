# Credential Caching Tests

This directory contains test scripts for validating and demonstrating the credential caching system functionality.

## Test Files

### Context Isolation Tests

#### `simple_context_test.py`
**Purpose**: Tests the context hash generation logic for credential isolation.

**What it tests**:
- Different credential configurations generate unique context hashes
- Azure Service Principal contexts are properly isolated by tenant/client
- Azure Managed Identity gets its own context
- Custom vault providers are isolated by provider name

**Usage**:
```bash
python3 tests/simple_context_test.py
```

**Expected Output**: Demonstrates 6 different credential contexts with unique hashes.

#### `test_context_isolation.py`
**Purpose**: More comprehensive context isolation testing (requires full module imports).

**What it tests**:
- Same functionality as simple_context_test.py but with full system integration
- Tests the actual runrobot.py context generation function

**Usage**:
```bash
python3 tests/test_context_isolation.py
```

### Logging and Monitoring Tests

#### `simple_logging_test.py`
**Purpose**: Tests the logging capabilities of the credential caching system.

**What it tests**:
- Cache info gathering functionality
- Comprehensive cache status logging
- Secret cache operations (hit/miss tracking)
- Cache clearing operations

**Usage**:
```bash
python3 tests/simple_logging_test.py
```

**Expected Output**: Demonstrates structured logging with CREDENTIAL_CACHE prefixes.

#### `test_logging.py`
**Purpose**: Comprehensive logging test with full system integration.

**What it tests**:
- Full Core.py integration with logging keywords
- Robot Framework keyword compatibility
- Complete logging workflow

**Usage**:
```bash
python3 tests/test_logging.py
```

**Note**: Requires additional dependencies (opentelemetry, etc.)

### Cache Functionality Tests

#### `test_credential_cache.py`
**Purpose**: Tests the actual credential caching functionality end-to-end.

**What it tests**:
- Secret fetching and caching
- Provider detection and routing
- Cache hit/miss behavior
- Error handling

**Usage**:
```bash
python3 tests/test_credential_cache.py
```

**Expected Output**: Demonstrates actual secret caching with different providers.

#### `cache_test.py`
**Purpose**: Simple cache functionality test.

**What it tests**:
- Basic cache info retrieval
- Simple cache operations

**Usage**:
```bash
python3 tests/cache_test.py
```

## Running All Tests

To run all tests that don't require heavy dependencies:
```bash
cd /home/runwhen/platform-robot-runtime/build-artifacts
python3 tests/simple_context_test.py
python3 tests/simple_logging_test.py
python3 tests/cache_test.py
```

To run tests that require full system (may need additional dependencies):
```bash
python3 tests/test_context_isolation.py
python3 tests/test_logging.py
python3 tests/test_credential_cache.py
```

## Test Categories

### 1. Unit Tests
- `simple_context_test.py` - Context hash generation logic
- `simple_logging_test.py` - Logging functionality
- `cache_test.py` - Basic cache operations

### 2. Integration Tests
- `test_context_isolation.py` - Full context isolation system
- `test_logging.py` - Complete logging system
- `test_credential_cache.py` - End-to-end credential caching

## Expected Test Results

### Context Isolation
- ✅ Different Azure tenants get different context hashes
- ✅ Different Azure service principals get different context hashes
- ✅ Azure Managed Identity gets unique context
- ✅ Custom vault providers are isolated by name

### Logging System
- ✅ Structured logging with consistent prefixes
- ✅ Cache hit/miss tracking
- ✅ Directory statistics collection
- ✅ Environment variable analysis

### Cache Functionality
- ✅ Filesystem-based credential persistence
- ✅ Context-isolated directory creation
- ✅ Provider-specific authentication handling
- ✅ Error handling and fallback behavior

## Troubleshooting Test Issues

### Common Issues

1. **Missing Dependencies**:
   ```bash
   pip3 install requests hvac azure-identity azure-mgmt-containerservice azure-mgmt-resource azure-mgmt-subscription PyYAML robotframework backoff prometheus_client
   ```

2. **Permission Issues**:
   ```bash
   mkdir -p /tmp/test_runwhen
   chmod 755 /tmp/test_runwhen
   ```

3. **Module Import Errors**:
   - Ensure you're running from the build-artifacts directory
   - Check that the RW module directory exists and is accessible

#### `test_filesystem_kubeconfig_cache.py`
**Purpose**: Tests the filesystem-based kubeconfig caching that persists across process boundaries.

**What it tests**:
- First kubeconfig request generates content and caches to filesystem
- Second request (after clearing in-memory cache) uses filesystem cache
- Cache files are created in the Azure config directory with proper naming
- Cache expiration works correctly (1-hour TTL)
- Performance improvement on cache hits

**Usage**:
```bash
python3 tests/test_filesystem_kubeconfig_cache.py
```

**Expected Output**:
- First request creates filesystem cache file
- Second request uses filesystem cache (no API calls)
- Cache expiration properly regenerates content
- Significant performance improvement for cached requests

### Debug Mode

To see detailed logging during tests:
```bash
export RW_LOG_LEVEL=DEBUG
python3 tests/simple_logging_test.py
``` 