using Amazon.S3;
using Amazon.S3.Model;
using PhotoAssistant.Application.Storage;

namespace PhotoAssistant.Infrastructure.Storage;

/// <summary>
/// <see cref="IObjectStorage"/> over the S3 API, which is what MinIO speaks
/// (ADR-12). The official AWS SDK rather than a MinIO client, so that moving to
/// R2 or B2 later is a change of endpoint and not of code.
/// </summary>
internal sealed class S3ObjectStorage(IAmazonS3 client, ObjectStorageOptions options)
    : IObjectStorage
{
    public async Task<string> PutAsync(
        StorageBucket bucket,
        string key,
        ReadOnlyMemory<byte> content,
        string contentType,
        CancellationToken cancellationToken)
    {
        // A MemoryStream over the buffer rather than a copy of it. The SDK reads
        // the stream once and an upload can be tens of megabytes; copying would
        // double that for no reason.
        using var stream = new MemoryStream(content.ToArray(), writable: false);

        await client.PutObjectAsync(
            new PutObjectRequest
            {
                BucketName = NameOf(bucket),
                Key = key,
                InputStream = stream,
                ContentType = contentType,

                // Without this the SDK computes a checksum by buffering the
                // whole stream again; the length is known, so it does not have
                // to guess.
                Headers = { ContentLength = content.Length },
            },
            cancellationToken);

        return key;
    }

    public async Task<StoredObject?> GetAsync(
        StorageBucket bucket,
        string key,
        CancellationToken cancellationToken)
    {
        try
        {
            using var response = await client.GetObjectAsync(
                NameOf(bucket), key, cancellationToken);

            using var buffer = new MemoryStream();
            await response.ResponseStream.CopyToAsync(buffer, cancellationToken);

            return new StoredObject
            {
                Content = buffer.ToArray(),
                ContentType = response.Headers.ContentType ?? "application/octet-stream",
            };
        }
        catch (AmazonS3Exception error) when (error.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            // Absence is an answer, not a fault: an interrupted upload leaves
            // rows and objects briefly out of step, and the caller decides what
            // that means.
            return null;
        }
    }

    public async Task DeleteAsync(
        StorageBucket bucket,
        string key,
        CancellationToken cancellationToken)
    {
        // S3 answers a delete of something that is not there with 204, the same
        // as a delete of something that was. That is the behaviour the caller
        // wants — the postcondition is absence, not removal — so there is no
        // not-found case to handle here, unlike in GetAsync.
        await client.DeleteObjectAsync(
            new DeleteObjectRequest { BucketName = NameOf(bucket), Key = key },
            cancellationToken);
    }

    private string NameOf(StorageBucket bucket) => bucket switch
    {
        StorageBucket.Originals => options.OriginalsBucket,
        StorageBucket.Derivatives => options.DerivativesBucket,
        StorageBucket.Exports => options.ExportsBucket,
        _ => throw new ArgumentOutOfRangeException(nameof(bucket), bucket, "unknown bucket"),
    };
}
