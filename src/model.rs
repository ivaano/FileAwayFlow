use serde::{Deserialize, Serialize};
#[allow(non_snake_case)]
#[derive(Debug, Deserialize, Serialize, Clone)]
pub  struct FileMoveRequest {
    pub sourcePath: String,
    pub targetPath: String,
}

#[derive(Serialize)]
pub struct GenericResponse {
    pub status: String,
    pub message: String,
}

#[derive(Serialize)]
pub struct HealthResponse {
    pub status: String,
    pub version: String,
    pub message: String,
}

#[derive(Debug)]
pub struct ApiKeyError;