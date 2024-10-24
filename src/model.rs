use serde::{Deserialize, Serialize};
#[allow(non_snake_case)]
#[derive(Debug, Deserialize, Serialize, Clone)]
pub  struct FileMoveRequest {
    pub sourcePath: String,
    pub targetPath: String,
}