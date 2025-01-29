use std::fs;
use std::path::Path;
use warp::{http::StatusCode, reject, reply, reply::json, Reply};
use crate::{ApiKeyError, GenericResponse, WebResult};
use crate::model::FileMoveRequest;

pub async fn health_checker_handler() -> WebResult<impl Reply> {
    const MESSAGE: &str = "FileAwayFlow API is up and running";

    let response_json = &GenericResponse {
        status: "success".to_string(),
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

    let move_result = match fs::rename(source_path, target_path) {
        Ok(_) => Ok(()),
        Err(err) => {
            if err.to_string().contains("invalid cross-device link") {
                match fs::copy(source_path, target_path) {
                    Ok(_) => {
                        fs::remove_file(source_path)
                    }
                    Err(e) => Err(e),
                }
            } else {
                Err(err)
            }
        }
    };

    if let Err(err) = move_result {
        return Err(reject::custom(FileSystemError(
            format!("Failed to move file: {}", err)
        )));
    }

    let json_response = &GenericResponse {
        status: "success".to_string(),
        message: format!("File {} moved successfully", file_move_request.sourcePath).to_string(),
    };

    Ok(json(&json_response))
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