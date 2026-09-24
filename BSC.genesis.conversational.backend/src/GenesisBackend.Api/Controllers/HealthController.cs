using Microsoft.AspNetCore.Mvc;

namespace GenesisBackend.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class HealthController : ControllerBase
{
    [HttpGet]
    public IActionResult Get() => Ok(new { status = "Healthy" });

    [HttpGet("live")]
    public IActionResult Live() => Ok(new { status = "Live" });

    [HttpGet("ready")]
    public IActionResult Ready() => Ok(new { status = "Ready" });
}
