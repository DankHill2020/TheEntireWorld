#include "AIStudioBridgeLibrary.h"

#if WITH_EDITOR
#include "Editor.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/ActorComponent.h"
#include "Animation/AnimInstance.h"
#include "Animation/AnimSequence.h"
#include "GameFramework/Actor.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerInput.h"
#include "UObject/UnrealType.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#endif

static FString AIStudioJsonString(const TSharedRef<FJsonObject>& Object)
{
    FString Output;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(Object, Writer);
    return Output;
}

FString UAIStudioBridgeLibrary::InspectAnimBlueprintGraph(UAnimBlueprint* AnimBlueprint)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("inspect_anim_blueprint_graph"));
    Root->SetBoolField(TEXT("ok"), false);

#if WITH_EDITOR
    if (!AnimBlueprint)
    {
        Root->SetStringField(TEXT("error"), TEXT("AnimBlueprint was null."));
        return AIStudioJsonString(Root);
    }

    Root->SetBoolField(TEXT("ok"), true);
    Root->SetStringField(TEXT("asset_name"), AnimBlueprint->GetName());
    Root->SetStringField(TEXT("asset_path"), AnimBlueprint->GetPathName());

    TArray<UEdGraph*> Graphs;
    Graphs.Append(AnimBlueprint->UbergraphPages);
    Graphs.Append(AnimBlueprint->FunctionGraphs);
    Graphs.Append(AnimBlueprint->MacroGraphs);
    Graphs.Append(AnimBlueprint->DelegateSignatureGraphs);

    TArray<TSharedPtr<FJsonValue>> GraphValues;
    for (UEdGraph* Graph : Graphs)
    {
        if (!Graph)
        {
            continue;
        }

        const TSharedRef<FJsonObject> GraphObject = MakeShared<FJsonObject>();
        GraphObject->SetStringField(TEXT("name"), Graph->GetName());
        GraphObject->SetStringField(TEXT("class"), Graph->GetClass()->GetName());

        TArray<TSharedPtr<FJsonValue>> NodeValues;
        for (UEdGraphNode* Node : Graph->Nodes)
        {
            if (!Node)
            {
                continue;
            }

            const TSharedRef<FJsonObject> NodeObject = MakeShared<FJsonObject>();
            NodeObject->SetStringField(TEXT("name"), Node->GetName());
            NodeObject->SetStringField(TEXT("title"), Node->GetNodeTitle(ENodeTitleType::ListView).ToString());
            NodeObject->SetStringField(TEXT("class"), Node->GetClass()->GetName());
            NodeObject->SetNumberField(TEXT("pin_count"), Node->Pins.Num());

            TArray<TSharedPtr<FJsonValue>> PinValues;
            for (UEdGraphPin* Pin : Node->Pins)
            {
                if (!Pin)
                {
                    continue;
                }
                const TSharedRef<FJsonObject> PinObject = MakeShared<FJsonObject>();
                PinObject->SetStringField(TEXT("name"), Pin->PinName.ToString());
                PinObject->SetStringField(TEXT("direction"), Pin->Direction == EGPD_Input ? TEXT("input") : TEXT("output"));
                PinObject->SetStringField(TEXT("category"), Pin->PinType.PinCategory.ToString());
                PinObject->SetNumberField(TEXT("linked_to_count"), Pin->LinkedTo.Num());
                PinValues.Add(MakeShared<FJsonValueObject>(PinObject));
            }
            NodeObject->SetArrayField(TEXT("pins"), PinValues);
            NodeValues.Add(MakeShared<FJsonValueObject>(NodeObject));
        }

        GraphObject->SetNumberField(TEXT("node_count"), Graph->Nodes.Num());
        GraphObject->SetArrayField(TEXT("nodes"), NodeValues);
        GraphValues.Add(MakeShared<FJsonValueObject>(GraphObject));
    }

    Root->SetArrayField(TEXT("graphs"), GraphValues);
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.inspect_anim_blueprint_graph(anim_bp)"));
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif

    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::InspectAnimationSequence(UAnimSequence* Animation)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("inspect_animation_sequence"));
    Root->SetBoolField(TEXT("ok"), Animation != nullptr);
    if (!Animation)
    {
        Root->SetStringField(TEXT("error"), TEXT("Animation was null."));
        return AIStudioJsonString(Root);
    }

    Root->SetStringField(TEXT("asset_name"), Animation->GetName());
    Root->SetStringField(TEXT("asset_path"), Animation->GetPathName());
    Root->SetStringField(TEXT("skeleton"), Animation->GetSkeleton() ? Animation->GetSkeleton()->GetPathName() : TEXT(""));
    Root->SetNumberField(TEXT("play_length_seconds"), Animation->GetPlayLength());
    Root->SetNumberField(TEXT("sampled_keys"), Animation->GetNumberOfSampledKeys());
    Root->SetNumberField(TEXT("sample_rate_fps"), Animation->GetSamplingFrameRate().AsDecimal());
    Root->SetBoolField(TEXT("has_root_motion"), Animation->HasRootMotion());
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.inspect_animation_sequence(animation)"));
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::InspectCharacterInPIE(UClass* CharacterClass, FString ExpectedAnimClassContains, const TArray<FName>& PropertyNames)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("inspect_character_in_pie"));
    Root->SetBoolField(TEXT("ok"), false);

#if WITH_EDITOR
    if (!GEditor || !GEditor->PlayWorld || !CharacterClass)
    {
        Root->SetStringField(TEXT("error"), TEXT("Active PIE world and CharacterClass are required."));
        return AIStudioJsonString(Root);
    }

    AActor* RuntimeActor = nullptr;
    for (TActorIterator<AActor> It(GEditor->PlayWorld); It; ++It)
    {
        if (*It && It->IsA(CharacterClass))
        {
            RuntimeActor = *It;
            break;
        }
    }
    if (!RuntimeActor)
    {
        Root->SetStringField(TEXT("error"), TEXT("No runtime actor of CharacterClass was found in PIE."));
        return AIStudioJsonString(Root);
    }

    Root->SetStringField(TEXT("actor"), RuntimeActor->GetName());
    Root->SetStringField(TEXT("actor_class"), RuntimeActor->GetClass()->GetPathName());
    Root->SetStringField(TEXT("location"), RuntimeActor->GetActorLocation().ToString());
    Root->SetStringField(TEXT("velocity"), RuntimeActor->GetVelocity().ToString());

    if (const ACharacter* Character = Cast<ACharacter>(RuntimeActor))
    {
        if (const UCharacterMovementComponent* Movement = Character->GetCharacterMovement())
        {
            Root->SetStringField(TEXT("movement_mode"), Movement->GetMovementName());
            Root->SetNumberField(TEXT("gravity_scale"), Movement->GravityScale);
        }
    }

    UAnimInstance* SelectedAnimInstance = nullptr;
    TArray<USkeletalMeshComponent*> Meshes;
    RuntimeActor->GetComponents(Meshes);
    for (USkeletalMeshComponent* Mesh : Meshes)
    {
        UAnimInstance* Instance = Mesh ? Mesh->GetAnimInstance() : nullptr;
        const FString ClassPath = Instance ? Instance->GetClass()->GetPathName() : TEXT("");
        if (Instance && (ExpectedAnimClassContains.IsEmpty() || ClassPath.Contains(ExpectedAnimClassContains)))
        {
            SelectedAnimInstance = Instance;
            Root->SetStringField(TEXT("anim_class"), ClassPath);
            if (UAnimMontage* ActiveMontage = Instance->GetCurrentActiveMontage())
            {
                Root->SetStringField(TEXT("active_montage"), ActiveMontage->GetPathName());
                Root->SetNumberField(TEXT("active_montage_position"), Instance->Montage_GetPosition(ActiveMontage));
            }
            break;
        }
    }

    const TSharedRef<FJsonObject> Properties = MakeShared<FJsonObject>();
    const TSharedRef<FJsonObject> PropertyOwners = MakeShared<FJsonObject>();
    for (const FName PropertyName : PropertyNames)
    {
        UObject* Owner = RuntimeActor;
        FProperty* Property = FindFProperty<FProperty>(Owner->GetClass(), PropertyName);
        if (!Property)
        {
            TInlineComponentArray<UActorComponent*> Components(RuntimeActor);
            for (UActorComponent* Component : Components)
            {
                if (!Component)
                {
                    continue;
                }
                Property = FindFProperty<FProperty>(Component->GetClass(), PropertyName);
                if (Property)
                {
                    Owner = Component;
                    break;
                }
            }
        }
        if (!Property && SelectedAnimInstance)
        {
            Owner = SelectedAnimInstance;
            Property = FindFProperty<FProperty>(Owner->GetClass(), PropertyName);
        }
        if (!Property)
        {
            Properties->SetStringField(PropertyName.ToString(), TEXT("<missing>"));
            PropertyOwners->SetStringField(PropertyName.ToString(), TEXT("<missing>"));
            continue;
        }
        FString Value;
        Property->ExportTextItem_Direct(Value, Property->ContainerPtrToValuePtr<void>(Owner), nullptr, Owner, PPF_None);
        Properties->SetStringField(PropertyName.ToString(), Value);
        PropertyOwners->SetStringField(PropertyName.ToString(), Owner->GetPathName());
    }
    Root->SetObjectField(TEXT("properties"), Properties);
    Root->SetObjectField(TEXT("property_owners"), PropertyOwners);
    Root->SetBoolField(TEXT("anim_instance_matched"), SelectedAnimInstance != nullptr);
    Root->SetBoolField(TEXT("ok"), SelectedAnimInstance != nullptr || ExpectedAnimClassContains.IsEmpty());
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.inspect_character_in_pie(character_class, expected_anim_class_contains, property_names)"));
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::ValidateCharacterMontagesInPIE(UClass* CharacterClass, const TArray<UAnimMontage*>& Montages, FString ExpectedAnimClassContains)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("validate_character_montages_in_pie"));
    Root->SetBoolField(TEXT("ok"), false);

#if WITH_EDITOR
    if (!GEditor || !GEditor->PlayWorld)
    {
        Root->SetStringField(TEXT("error"), TEXT("No active PIE world was found."));
        return AIStudioJsonString(Root);
    }
    if (!CharacterClass)
    {
        Root->SetStringField(TEXT("error"), TEXT("CharacterClass was null."));
        return AIStudioJsonString(Root);
    }

    UWorld* World = GEditor->PlayWorld;
    Root->SetStringField(TEXT("world"), World ? World->GetName() : TEXT(""));
    Root->SetStringField(TEXT("character_class"), CharacterClass->GetPathName());

    AActor* RuntimeActor = nullptr;
    for (TActorIterator<AActor> It(World); It; ++It)
    {
        AActor* Candidate = *It;
        if (Candidate && Candidate->IsA(CharacterClass))
        {
            RuntimeActor = Candidate;
            break;
        }
    }

    if (!RuntimeActor)
    {
        Root->SetStringField(TEXT("error"), TEXT("No runtime actor of CharacterClass was found in PIE."));
        return AIStudioJsonString(Root);
    }
    Root->SetStringField(TEXT("actor"), RuntimeActor->GetName());
    Root->SetStringField(TEXT("actor_class"), RuntimeActor->GetClass()->GetPathName());

    TArray<USkeletalMeshComponent*> Meshes;
    RuntimeActor->GetComponents(Meshes);

    UAnimInstance* SelectedAnimInstance = nullptr;
    TArray<TSharedPtr<FJsonValue>> ComponentValues;
    for (USkeletalMeshComponent* Mesh : Meshes)
    {
        if (!Mesh)
        {
            continue;
        }
        UAnimInstance* AnimInstance = Mesh->GetAnimInstance();
        const FString AnimClassPath = AnimInstance ? AnimInstance->GetClass()->GetPathName() : TEXT("");
        const bool bMatchesExpected = ExpectedAnimClassContains.IsEmpty() || AnimClassPath.Contains(ExpectedAnimClassContains);

        const TSharedRef<FJsonObject> ComponentObject = MakeShared<FJsonObject>();
        ComponentObject->SetStringField(TEXT("name"), Mesh->GetName());
        ComponentObject->SetStringField(TEXT("skeletal_mesh"), Mesh->GetSkeletalMeshAsset() ? Mesh->GetSkeletalMeshAsset()->GetPathName() : TEXT(""));
        ComponentObject->SetStringField(TEXT("anim_class"), AnimClassPath);
        ComponentObject->SetBoolField(TEXT("matches_expected_anim_class"), bMatchesExpected);
        ComponentValues.Add(MakeShared<FJsonValueObject>(ComponentObject));

        if (!SelectedAnimInstance && AnimInstance && bMatchesExpected)
        {
            SelectedAnimInstance = AnimInstance;
        }
    }
    Root->SetArrayField(TEXT("components"), ComponentValues);

    if (!SelectedAnimInstance)
    {
        Root->SetStringField(TEXT("error"), TEXT("No runtime AnimInstance matched ExpectedAnimClassContains."));
        return AIStudioJsonString(Root);
    }
    Root->SetStringField(TEXT("selected_anim_class"), SelectedAnimInstance->GetClass()->GetPathName());

    bool bAllMontagesPlayable = Montages.Num() > 0;
    TArray<TSharedPtr<FJsonValue>> MontageValues;
    for (UAnimMontage* Montage : Montages)
    {
        const TSharedRef<FJsonObject> MontageObject = MakeShared<FJsonObject>();
        MontageObject->SetBoolField(TEXT("asset_exists"), Montage != nullptr);
        MontageObject->SetStringField(TEXT("asset_path"), Montage ? Montage->GetPathName() : TEXT(""));
        float PlayResult = 0.0f;
        bool bActive = false;
        bool bPlaying = false;
        if (Montage)
        {
            PlayResult = SelectedAnimInstance->Montage_Play(Montage, 1.0f);
            bActive = SelectedAnimInstance->Montage_IsActive(Montage);
            bPlaying = SelectedAnimInstance->Montage_IsPlaying(Montage);
            SelectedAnimInstance->Montage_Stop(0.0f, Montage);
        }
        MontageObject->SetNumberField(TEXT("play_result"), PlayResult);
        MontageObject->SetBoolField(TEXT("active_after_play"), bActive);
        MontageObject->SetBoolField(TEXT("playing_after_play"), bPlaying);
        const bool bPlayable = Montage && PlayResult > 0.0f && (bActive || bPlaying);
        MontageObject->SetBoolField(TEXT("playable"), bPlayable);
        bAllMontagesPlayable = bAllMontagesPlayable && bPlayable;
        MontageValues.Add(MakeShared<FJsonValueObject>(MontageObject));
    }
    Root->SetArrayField(TEXT("montages"), MontageValues);
    Root->SetBoolField(TEXT("ok"), bAllMontagesPlayable);
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.validate_character_montages_in_pie(character_class, montages, expected_anim_class_contains)"));
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif

    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::InjectKeyInPIE(FKey Key, bool bPressed)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("inject_key_in_pie"));
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(TEXT("key"), Key.ToString());
    Root->SetBoolField(TEXT("pressed"), bPressed);

#if WITH_EDITOR
    if (!GEditor || !GEditor->PlayWorld)
    {
        Root->SetStringField(TEXT("error"), TEXT("No active PIE world was found."));
        return AIStudioJsonString(Root);
    }
    APlayerController* Controller = GEditor->PlayWorld->GetFirstPlayerController();
    if (!Controller)
    {
        Root->SetStringField(TEXT("error"), TEXT("No PIE player controller was found."));
        return AIStudioJsonString(Root);
    }
    const EInputEvent Event = bPressed ? IE_Pressed : IE_Released;
    const FInputKeyParams InputParams(Key, Event, bPressed ? 1.0 : 0.0, Key.IsGamepadKey());
    const bool bHandled = Controller->InputKey(InputParams);
    Root->SetStringField(TEXT("controller"), Controller->GetPathName());
    Root->SetBoolField(TEXT("handled"), bHandled);
    Root->SetBoolField(TEXT("ok"), true);
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.inject_key_in_pie(key, pressed)"));
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif
    return AIStudioJsonString(Root);
}
