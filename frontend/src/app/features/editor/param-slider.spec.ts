import { ComponentFixture, TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { provideTranslations } from '../../core/i18n/translation.config';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

import { PARAMS } from './editor-params';
import { ParamSlider } from './param-slider';

const CONTRAST = PARAMS.find((param) => param.key === 'contrast')!;

describe('ParamSlider', () => {
  let fixture: ComponentFixture<ParamSlider>;

  async function mount(value: number): Promise<void> {
    await TestBed.configureTestingModule({
      imports: [ParamSlider],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideTranslations()],
    }).compileComponents();

    fixture = TestBed.createComponent(ParamSlider);
    fixture.componentRef.setInput('param', CONTRAST);
    fixture.componentRef.setInput('value', value);
    fixture.detectChanges();
  }

  afterEach(() => TestBed.resetTestingModule());

  function element(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function head(): HTMLElement {
    return element().querySelector<HTMLElement>('.param__head')!;
  }

  /** A pointer event as jsdom can make one: it has no PointerEvent of its own. */
  function pointerDown(type: string): Event {
    const event = new Event('pointerdown', { bubbles: true });
    Object.defineProperty(event, 'pointerType', { value: type });

    return event;
  }

  it('prints the value with its sign, so the direction is read once', async () => {
    await mount(18);

    expect(element().querySelector('.param__value')!.textContent?.trim()).toBe('+18');
  });

  it('offers nothing to reset when the parameter is already neutral', async () => {
    await mount(0);

    expect(element().querySelector<HTMLButtonElement>('.param__value')!.disabled).toBe(true);
  });

  it('a double click asks for a reset', async () => {
    await mount(18);
    const asked = vi.fn();
    fixture.componentInstance.resetRequested.subscribe(asked);

    head().dispatchEvent(new MouseEvent('dblclick'));

    expect(asked).toHaveBeenCalled();
  });

  it('a finger resting on the row asks for the same thing, since a tap cannot', async () => {
    // The double click has no equivalent on a touch screen: the second tap
    // arrives as a separate tap. Task 4 names the long press as its stand-in.
    vi.useFakeTimers();
    await mount(18);
    const asked = vi.fn();
    fixture.componentInstance.resetRequested.subscribe(asked);

    head().dispatchEvent(pointerDown('touch'));
    vi.advanceTimersByTime(600);

    expect(asked).toHaveBeenCalled();
    vi.useRealTimers();
  });

  it('a mouse held still is a person thinking, not a request', async () => {
    vi.useFakeTimers();
    await mount(18);
    const asked = vi.fn();
    fixture.componentInstance.resetRequested.subscribe(asked);

    head().dispatchEvent(pointerDown('mouse'));
    vi.advanceTimersByTime(600);

    expect(asked).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it('a finger that lifts in time changes nothing', async () => {
    vi.useFakeTimers();
    await mount(18);
    const asked = vi.fn();
    fixture.componentInstance.resetRequested.subscribe(asked);

    head().dispatchEvent(pointerDown('touch'));
    vi.advanceTimersByTime(200);
    head().dispatchEvent(new Event('pointerup'));
    vi.advanceTimersByTime(600);

    expect(asked).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it('a key that moves the value opens a step, and Tab does not', async () => {
    await mount(18);
    const started = vi.fn();
    fixture.componentInstance.stepStart.subscribe(started);

    const track = element().querySelector('.param__track')!;

    track.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab' }));
    expect(started).not.toHaveBeenCalled();

    track.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
    expect(started).toHaveBeenCalled();
  });
});
