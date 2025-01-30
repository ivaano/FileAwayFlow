use std::fs;
use std::path::Path;
use warp::{http::StatusCode, reject, reply, reply::json, Reply};
use crate::{ApiKeyError, GenericResponse, HealthResponse, WebResult};
use crate::model::FileMoveRequest;


pub async fn health_checker_handler() -> WebResult<impl Reply> {
    const MESSAGE: &str = "FileAwayFlow API is up and running.";

    let response_json = &HealthResponse {
        status: "healthy".to_string(),
        version: env!("CARGO_PKG_VERSION").to_string(),
        message: MESSAGE.to_string(),
    };
    Ok(json(response_json))
}

pub async fn handle_rejection(err: reject::Rejection) -> Result<reply::Response, warp::Rejection> {
    if let Some(_) = err.find::<ApiKeyError>() {
        let json_response = &GenericResponse {
            status: "error".to_string(),
            message: "Invalid API key".to_string(),
        };
        return Ok(reply::with_status(json(&json_response), StatusCode::FORBIDDEN).into_response());
    }


    if let Some(file_not_found_error) = err.find::<FileNotFoundError>().cloned() {
        let message = file_not_found_error.message();
        let json_response = &GenericResponse {
            status: "error".to_string(),
            message: format!("{}", message).to_string(),
        };
        return Ok(reply::with_status(json(&json_response), StatusCode::BAD_REQUEST).into_response());
    }


    let json_response = &GenericResponse {
        status: "error".to_string(),
        message: format!("Unhandled rejection: {:?}", err).to_string(),
    };
    Ok(reply::with_status(json(&json_response), StatusCode::BAD_REQUEST).into_response())
}


pub async fn handle_file_move(file_move_request: FileMoveRequest) -> WebResult<impl Reply> {
    let source_path = Path::new(&file_move_request.sourcePath);
    let target_path = Path::new(&file_move_request.targetPath);

    if !source_path.exists() {
        return Err(reject::custom(FileNotFoundError(format!("File not found: {}", file_move_request.sourcePath))));
    }

    if target_path.exists() {
        return Err(reject::custom(FileAlreadyExistsError));
    }

    match fs::rename(source_path, target_path) {
        Ok(_) => (),
        Err(_) => {
            // If rename fails, try copy + delete
            if source_path.is_dir() {
                if let Err(err) = copy_dir_recursive(source_path, target_path) {
                    return Err(reject::custom(FileSystemError(
                        format!("Failed to copy directory: {}", err)
                    )));
                }
                if let Err(err) = fs::remove_dir_all(source_path) {
                    return Err(reject::custom(FileSystemError(
                        format!("Failed to remove source directory after copy: {}", err)
                    )));
                }
            } else {
                if let Err(err) = fs::copy(source_path, target_path) {
                    return Err(reject::custom(FileSystemError(
                        format!("Failed to copy file: {}", err)
                    )));
                }
                if let Err(err) = fs::remove_file(source_path) {
                    return Err(reject::custom(FileSystemError(
                        format!("Failed to remove source file after copy: {}", err)
                    )));
                }
            }
        }
    };

    let json_response = &GenericResponse {
        status: "success".to_string(),
        message: format!("File {} moved successfully", file_move_request.sourcePath).to_string(),
    };

    Ok(json(&json_response))
}

fn copy_dir_recursive(src: impl AsRef<Path>, dst: impl AsRef<Path>) -> std::io::Result<()> {
    fs::create_dir_all(&dst)?;

    for entry in fs::read_dir(src.as_ref())? {
        let entry = entry?;
        let entry_type = entry.file_type()?;
        let src_path = entry.path();
        let dst_path = dst.as_ref().join(entry.file_name());

        if entry_type.is_dir() {
            copy_dir_recursive(&src_path, &dst_path)?;
        } else {
            fs::copy(&src_path, &dst_path)?;
        }
    }

    Ok(())
}


trait ErrorMessage {
    fn message(&self) -> &str;
}

impl ErrorMessage for FileNotFoundError {
    fn message(&self) -> &str {
        &self.0
    }
}
#[derive(Debug, Clone)]
struct FileNotFoundError(String);

impl reject::Reject for FileNotFoundError {}

#[derive(Debug, Clone)]
struct FileSystemError(String);

impl reject::Reject for FileSystemError {}

impl ErrorMessage for FileSystemError {
    fn message(&self) -> &str {
        &self.0
    }
}


#[derive(Debug)]
struct FileAlreadyExistsError;

impl reject::Reject for FileAlreadyExistsError {}