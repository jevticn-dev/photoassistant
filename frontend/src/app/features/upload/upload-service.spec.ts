import { HttpEventType, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { environment } from '../../../environments/environment';
import {
  MAXIMUM_BYTES,
  UploadFailure,
  UploadProgress,
  UploadService,
  fileError,
} from './upload-service';

const ENDPOINT = `${environment.apiBaseUrl}/photos`;

const PHOTO = {
  projectId: '0199a1f0-0000-7000-8000-000000000001',
  photoId: '0199a1f0-0000-7000-8000-000000000002',
  name: 'Alpine Ridge',
  width: 3000,
  height: 2000,
};

describe('UploadService', () => {
  let service: UploadService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });

    service = TestBed.inject(UploadService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function file(name = 'alpine.jpg'): File {
    return new File([new Uint8Array([1, 2, 3])], name, { type: 'image/jpeg' });
  }

  function sized(bytes: number, type = 'image/jpeg'): File {
    // A real buffer, so `size` is what a browser would report.
    return new File([new Uint8Array(bytes)], 'big.jpg', { type });
  }

  it('refuses an oversized file without sending it', () => {
    // The reason this is checked here at all: Kestrel drops the connection
    // when the body exceeds its limit, so the browser sees a network error and
    // the person is told to check their connection about a file that is simply
    // too big. Nothing must go out.
    let failure: UploadFailure | undefined;

    service
      .upload(sized(MAXIMUM_BYTES + 1))
      .subscribe({ error: (error: UploadFailure) => (failure = error) });

    expect(failure?.summaryKey).toBe('upload.errors.tooLarge');
    http.expectNone(ENDPOINT);
  });

  it('accepts a file exactly on the limit', () => {
    // Off-by-one at a boundary a person can hit deliberately.
    service.upload(sized(MAXIMUM_BYTES)).subscribe();

    http.expectOne(ENDPOINT).flush(PHOTO);
  });

  it('refuses a kind the server cannot decode, which drag and drop can still deliver', () => {
    // The input's `accept` filters the picker; dropping a file ignores it.
    let failure: UploadFailure | undefined;

    service
      .upload(sized(1024, 'application/pdf'))
      .subscribe({ error: (error: UploadFailure) => (failure = error) });

    expect(failure?.summaryKey).toBe('upload.errors.wrongType');
    http.expectNone(ENDPOINT);
  });

  it('refuses an empty file', () => {
    let failure: UploadFailure | undefined;

    service.upload(sized(0)).subscribe({ error: (error: UploadFailure) => (failure = error) });

    expect(failure?.summaryKey).toBe('upload.errors.empty');
    http.expectNone(ENDPOINT);
  });

  it('sends the file under the field name the controller binds', () => {
    // A mismatch here binds null on the server and produces a validation error
    // with no obvious cause, so the name is worth asserting.
    service.upload(file()).subscribe();

    const request = http.expectOne(ENDPOINT);
    const body = request.request.body as FormData;

    expect(body.get('file')).toBeInstanceOf(File);
    expect((body.get('file') as File).name).toBe('alpine.jpg');
    request.flush(PHOTO);
  });

  it('never sits on a frozen zero when the browser reports no progress', () => {
    // The localhost case, and the one that was wrong: the body goes out in a
    // single write, so no useful UploadProgress arrives. Angular's `Sent` fires
    // when the request is dispatched, not when the bytes are out, so treating
    // it as "0% uploaded" left a stuck 0% across the whole server-side wait —
    // which is the part that actually takes seconds.
    const seen: UploadProgress[] = [];
    service.upload(file()).subscribe((progress) => seen.push(progress));

    http.expectOne(ENDPOINT).flush(PHOTO);

    expect(seen.some((progress) => progress.phase === 'sending')).toBe(false);
    expect(seen[0]).toEqual({ phase: 'processing' });
  });

  it('reports a real fraction while sending, and none afterwards', () => {
    const seen: UploadProgress[] = [];
    service.upload(file()).subscribe((progress) => seen.push(progress));

    const request = http.expectOne(ENDPOINT);
    request.event({ type: HttpEventType.UploadProgress, loaded: 25, total: 100 });
    request.flush(PHOTO);

    // Sent reads as processing; the percentage appears only once a measured
    // upload is genuinely in flight.
    expect(seen[0]).toEqual({ phase: 'processing' });
    expect(seen[1]).toEqual({ phase: 'sending', percent: 25 });
    expect(seen.at(-1)).toEqual({ phase: 'done', photo: PHOTO });
  });

  it('stops showing a percentage once the last byte is out', () => {
    // A bar frozen at 100% for the longest part of the wait is worse than no
    // bar: it says finished while the server is still working.
    const seen: UploadProgress[] = [];
    service.upload(file()).subscribe((progress) => seen.push(progress));

    const request = http.expectOne(ENDPOINT);
    request.event({ type: HttpEventType.UploadProgress, loaded: 100, total: 100 });
    request.flush(PHOTO);

    expect(seen).toContainEqual({ phase: 'processing' });
    expect(seen).not.toContainEqual({ phase: 'sending', percent: 100 });
  });

  it('treats an unmeasurable upload as processing rather than as zero per cent', () => {
    const seen: UploadProgress[] = [];
    service.upload(file()).subscribe((progress) => seen.push(progress));

    const request = http.expectOne(ENDPOINT);
    request.event({ type: HttpEventType.UploadProgress, loaded: 40 });
    request.flush(PHOTO);

    // A progress event with no total must produce no percentage at all rather
    // than a made-up one.
    expect(seen).toContainEqual({ phase: 'processing' });
    expect(seen.some((progress) => progress.phase === 'sending')).toBe(false);
  });

  it('passes the API wording for a rejected file straight through', () => {
    // It names the real limit or format, which a translated generic message
    // could not.
    let failure: UploadFailure | undefined;
    service.upload(file()).subscribe({ error: (error: UploadFailure) => (failure = error) });

    http
      .expectOne(ENDPOINT)
      .flush(
        { errors: { file: ['Only JPEG, PNG and WebP photographs can be uploaded.'] } },
        { status: 400, statusText: 'Bad Request' },
      );

    expect(fileError(failure ?? null)).toBe('Only JPEG, PNG and WebP photographs can be uploaded.');
    expect(failure?.summaryKey).toBeNull();
  });

  it('turns the server size limit into a message of our own', () => {
    // A 413 never reached the handler, so there is no field-keyed message.
    let failure: UploadFailure | undefined;
    service.upload(file()).subscribe({ error: (error: UploadFailure) => (failure = error) });

    http.expectOne(ENDPOINT).flush({}, { status: 413, statusText: 'Payload Too Large' });

    expect(failure?.summaryKey).toBe('upload.errors.tooLarge');
  });

  it('distinguishes an expired session from an unreachable server', () => {
    const failures: (UploadFailure | undefined)[] = [];

    service.upload(file()).subscribe({ error: (error: UploadFailure) => failures.push(error) });
    http.expectOne(ENDPOINT).flush({}, { status: 401, statusText: 'Unauthorized' });

    service.upload(file()).subscribe({ error: (error: UploadFailure) => failures.push(error) });
    http.expectOne(ENDPOINT).error(new ProgressEvent('error'), { status: 0, statusText: '' });

    expect(failures[0]?.summaryKey).toBe('upload.errors.signedOut');
    expect(failures[1]?.summaryKey).toBe('upload.errors.unreachable');
  });
});
