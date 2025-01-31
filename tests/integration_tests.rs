
use std::fs;
use serde_json::json;
use warp::test::request;
use tempfile::TempDir;
use file_away_flow::{health_checker, files_routes};
#[tokio::test]
async fn test_health_endpoint() {
    let api = health_checker();
    let response = request()
        .path("/api/health")
        .method("GET")
        .reply(&api)
        .await;

    assert_eq!(response.status(), 200);
    let response_json: serde_json::Value = serde_json::from_slice(response.body()).unwrap();
    assert_eq!(response_json["status"], "healthy");
    assert!(response_json["message"].as_str().unwrap().contains("FileAwayFlow API is up and running"));
}

#[tokio::test]
async fn test_file_move_success() {
    // Create temporary directory for test files
    let temp_dir = TempDir::new().unwrap();
    let source_path = temp_dir.path().join("test_file.txt");
    let target_path = temp_dir.path().join("moved_file.txt");

    // Create test file
    fs::write(&source_path, "test content").unwrap();

    let api = files_routes();
    let response = request()
        .path("/api/files/move")
        .method("POST")
        .header("X-API-KEY", "123456")
        .json(&json!({
            "sourcePath": source_path.to_str().unwrap(),
            "targetPath": target_path.to_str().unwrap()
        }))
        .reply(&api)
        .await;

    assert_eq!(response.status(), 200);
    let response_json: serde_json::Value = serde_json::from_slice(response.body()).unwrap();
    assert_eq!(response_json["status"], "success");

    // Verify file was actually moved
    assert!(!source_path.exists());
    assert!(target_path.exists());
    assert_eq!(fs::read_to_string(&target_path).unwrap(), "test content");
}

#[tokio::test]
async fn test_file_move_directory() {
    let temp_dir = TempDir::new().unwrap();
    let source_dir = temp_dir.path().join("test_dir");
    let target_dir = temp_dir.path().join("moved_dir");

    // Create test directory with some files
    fs::create_dir(&source_dir).unwrap();
    fs::write(source_dir.join("file1.txt"), "content1").unwrap();
    fs::write(source_dir.join("file2.txt"), "content2").unwrap();

    let api = files_routes();
    let response = request()
        .path("/api/files/move")
        .method("POST")
        .header("X-API-KEY", "123456")
        .json(&json!({
            "sourcePath": source_dir.to_str().unwrap(),
            "targetPath": target_dir.to_str().unwrap()
        }))
        .reply(&api)
        .await;

    assert_eq!(response.status(), 200);

    // Verify directory was moved with contents intact
    assert!(!source_dir.exists());
    assert!(target_dir.exists());
    assert!(target_dir.join("file1.txt").exists());
    assert!(target_dir.join("file2.txt").exists());
    assert_eq!(fs::read_to_string(target_dir.join("file1.txt")).unwrap(), "content1");
    assert_eq!(fs::read_to_string(target_dir.join("file2.txt")).unwrap(), "content2");
}

#[tokio::test]
async fn test_file_move_source_not_found() {
    let temp_dir = TempDir::new().unwrap();
    let source_path = temp_dir.path().join("nonexistent.txt");
    let target_path = temp_dir.path().join("target.txt");

    let api = files_routes();
    let response = request()
        .path("/api/files/move")
        .method("POST")
        .header("X-API-KEY", "123456")
        .json(&json!({
            "sourcePath": source_path.to_str().unwrap(),
            "targetPath": target_path.to_str().unwrap()
        }))
        .reply(&api)
        .await;

    assert_eq!(response.status(), 400);
    let response_json: serde_json::Value = serde_json::from_slice(response.body()).unwrap();
    assert_eq!(response_json["status"], "error");
    assert!(response_json["message"].as_str().unwrap().contains("File not found"));
}

#[tokio::test]
async fn test_invalid_api_key() {
    let temp_dir = TempDir::new().unwrap();
    let source_path = temp_dir.path().join("test.txt");
    let target_path = temp_dir.path().join("moved.txt");

    fs::write(&source_path, "test content").unwrap();

    let api = files_routes();
    let response = request()
        .path("/api/files/move")
        .method("POST")
        .header("X-API-KEY", "wrong_key")
        .json(&json!({
            "sourcePath": source_path.to_str().unwrap(),
            "targetPath": target_path.to_str().unwrap()
        }))
        .reply(&api)
        .await;

    assert_eq!(response.status(), 403);
    let response_json: serde_json::Value = serde_json::from_slice(response.body()).unwrap();
    assert_eq!(response_json["status"], "error");
    assert_eq!(response_json["message"], "Invalid API key");
}

#[tokio::test]
async fn test_file_move_target_exists() {
    let temp_dir = TempDir::new().unwrap();
    let source_path = temp_dir.path().join("source.txt");
    let target_path = temp_dir.path().join("target.txt");

    fs::write(&source_path, "source content").unwrap();
    fs::write(&target_path, "target content").unwrap();

    let api = files_routes();
    let response = request()
        .path("/api/files/move")
        .method("POST")
        .header("X-API-KEY", "123456")
        .json(&json!({
            "sourcePath": source_path.to_str().unwrap(),
            "targetPath": target_path.to_str().unwrap()
        }))
        .reply(&api)
        .await;

    assert_eq!(response.status(), 400);
    let response_json: serde_json::Value = serde_json::from_slice(response.body()).unwrap();
    assert_eq!(response_json["status"], "error");
}