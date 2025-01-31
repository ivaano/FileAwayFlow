mod handler;
mod model;
mod routes;

use warp::{Filter, Rejection, reject};
use lazy_static::lazy_static;
use std::env;

// Re-export all the types and functions needed for testing
pub use crate::handler::*;
pub use crate::model::*;
pub use crate::routes::*;

lazy_static! {
    pub static ref EXPECTED_API_KEY: String = env::var("API_KEY").unwrap_or("123456".to_string());
}

pub type WebResult<T> = Result<T, Rejection>;

impl reject::Reject for ApiKeyError {}

// Helper function for creating a test server instance
pub fn create_test_server() -> impl Filter<Extract = impl warp::Reply, Error = Rejection> + Clone {
    files_routes()
        .with(warp::cors()
            .allow_any_origin()
            .allow_methods(&[warp::http::Method::GET, warp::http::Method::POST])
            .allow_header("content-type")
            .allow_header("X-API-KEY"))
        .with(warp::log("api"))
}